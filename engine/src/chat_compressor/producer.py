"""C_t producers: hashed n-gram fallback, optional ST embed, optional HF gist."""

from __future__ import annotations

import hashlib
import os
import re
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from chat_compressor.chunks import chunk_text
from chat_compressor.compress import DEFAULT_D, DEFAULT_K_MAX, append_then_pool, live_mask

TOKEN_RE = re.compile(r"[A-Za-z0-9_']+")


def _chunk_text(text: str, max_chunks: int = 8) -> list[str]:
    """Compat wrapper — structure-aware chunker lives in chunks.py."""
    return chunk_text(text, max_chunks=max_chunks)


def hashed_ngram_embed(text: str, d: int = DEFAULT_D, seed: int = 0) -> np.ndarray:
    """Hash-stable mean-pooled n-gram projection. No model downloads."""
    vec = np.zeros((d,), dtype=np.float32)
    tokens = TOKEN_RE.findall(text.lower())
    if not tokens:
        tokens = ["empty"]
    for n in (1, 2, 3):
        for i in range(len(tokens) - n + 1):
            gram = " ".join(tokens[i : i + n])
            payload = f"{seed}:{n}:{gram}".encode("utf-8")
            digest = hashlib.blake2b(payload, digest_size=8).digest()
            idx = int.from_bytes(digest[:4], "little") % d
            sign = 1.0 if digest[4] % 2 == 0 else -1.0
            vec[idx] += sign
    norm = float(np.linalg.norm(vec))
    if norm > 0:
        vec /= norm
    return vec


@dataclass
class CompressResult:
    C: np.ndarray
    M: np.ndarray
    producer: str
    KV: np.ndarray | None = None


class EmbeddingProducer:
    """Default offline producer. Uses ST if EMBED_MODEL_PATH loads; else hashed."""

    def __init__(
        self,
        d: int = DEFAULT_D,
        k_max: int = DEFAULT_K_MAX,
        seed: int = 0,
        name: str = "embed",
    ) -> None:
        self.d = int(d)
        self.k_max = int(k_max)
        self.seed = int(seed)
        self.name = name
        self._st_model = None
        self._try_load_sentence_transformer()

    def _try_load_sentence_transformer(self) -> None:
        path = os.environ.get("EMBED_MODEL_PATH", "").strip()
        if not path:
            return
        try:
            from sentence_transformers import SentenceTransformer

            self._st_model = SentenceTransformer(path)
            self.d = int(self._st_model.get_sentence_embedding_dimension())
        except Exception:
            self._st_model = None

    def encode_rows(self, text: str) -> np.ndarray:
        chunks = _chunk_text(text)
        if self._st_model is not None:
            emb = np.asarray(self._st_model.encode(chunks), dtype=np.float32)
            return emb
        return np.stack([hashed_ngram_embed(c, d=self.d, seed=self.seed) for c in chunks])

    def compress(self, prev_c: np.ndarray | None, new_input: str) -> CompressResult:
        new_rows = self.encode_rows(new_input)
        c_t = append_then_pool(prev_c, new_rows, k_max=self.k_max)
        return CompressResult(C=c_t, M=live_mask(c_t.shape[0]), producer=self.name)


class GistHFProducer:
    """Optional local transformers gist model. Env-gated; never used by pytest."""

    def __init__(
        self,
        model_path: str,
        k_max: int = DEFAULT_K_MAX,
        name: str = "gist-hf",
    ) -> None:
        self.model_path = model_path
        self.k_max = int(k_max)
        self.name = name
        self.d = DEFAULT_D
        self._model = None
        self._tokenizer = None
        self._load()

    def _load(self) -> None:
        from transformers import AutoModel, AutoTokenizer

        self._tokenizer = AutoTokenizer.from_pretrained(self.model_path)
        self._model = AutoModel.from_pretrained(self.model_path)
        self._model.eval()
        self.d = int(self._model.config.hidden_size)

    def compress(self, prev_c: np.ndarray | None, new_input: str) -> CompressResult:
        import torch

        assert self._model is not None and self._tokenizer is not None
        tokens = self._tokenizer(
            new_input,
            return_tensors="pt",
            truncation=True,
            max_length=512,
        )
        with torch.no_grad():
            out = self._model(**tokens)
            hidden = out.last_hidden_state[0].cpu().numpy().astype(np.float32)
        # take last k gist-like positions (tail pooling)
        take = min(self.k_max, hidden.shape[0])
        new_rows = hidden[-take:]
        c_t = append_then_pool(prev_c, new_rows, k_max=self.k_max)
        kv = None
        if hasattr(out, "past_key_values") and out.past_key_values is not None:
            # store a compact last-layer K snapshot when present
            try:
                k_last = out.past_key_values[-1][0][0].cpu().numpy().astype(np.float32)
                kv = k_last[: c_t.shape[0]]
            except Exception:
                kv = None
        return CompressResult(C=c_t, M=live_mask(c_t.shape[0]), producer=self.name, KV=kv)


def make_producer(
    *,
    d: int = DEFAULT_D,
    k_max: int = DEFAULT_K_MAX,
    seed: int = 0,
    name: str = "embed",
) -> EmbeddingProducer | GistHFProducer:
    gist = os.environ.get("GIST_MODEL_PATH", "").strip()
    if gist and Path(gist).exists():
        return GistHFProducer(gist, k_max=k_max)
    return EmbeddingProducer(d=d, k_max=k_max, seed=seed, name=name)
