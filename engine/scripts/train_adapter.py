"""Train Pattern 2 gated-MLP adapter on parallel producer activations."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from chat_compressor.parse import parse_jsonl
from chat_compressor.producer import EmbeddingProducer
from chat_compressor.translate.adapter import GatedMLPAdapter


def collect_pairs(fixture: Path, d_a: int, d_b: int, k_max: int) -> tuple[list, list]:
    turns = parse_jsonl(fixture)
    prod_a = EmbeddingProducer(d=d_a, k_max=k_max, seed=0, name="embed-a")
    prod_b = EmbeddingProducer(d=d_b, k_max=k_max, seed=99, name="embed-b")
    c_a = None
    c_b = None
    xs, ys = [], []
    for turn in turns:
        ra = prod_a.compress(c_a, turn.text)
        rb = prod_b.compress(c_b, turn.text)
        c_a, c_b = ra.C, rb.C
        # align rows by min k
        k = min(c_a.shape[0], c_b.shape[0])
        xs.append(c_a[:k])
        ys.append(c_b[:k])
    return xs, ys


def train(
    fixture: Path,
    out: Path,
    d_a: int = 256,
    d_b: int = 128,
    r: int = 64,
    steps: int = 40,
    k_max: int = 32,
) -> Path:
    xs, ys = collect_pairs(fixture, d_a, d_b, k_max)
    adapter = GatedMLPAdapter(d_a=d_a, d_b=d_b, r=r)
    last = 0.0
    for step in range(steps):
        last = 0.0
        for x, y in zip(xs, ys):
            last += adapter.train_step(x, y)
        last /= max(len(xs), 1)
        if step == 0 or step == steps - 1 or step % 10 == 0:
            print(f"[PASS] train_step={step} loss={last:.6g}")
    out.parent.mkdir(parents=True, exist_ok=True)
    adapter.save(out)
    print(f"[PASS] adapter={out} d_a={d_a} d_b={d_b} r={r}")
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Train Pattern 2 adapter")
    parser.add_argument("--fixture", type=Path, default=ROOT / "fixtures" / "synthetic-generic.jsonl")
    parser.add_argument("--out", type=Path, default=ROOT / "state" / "adapters" / "embed-a_to_embed-b.pt")
    parser.add_argument("--d-a", type=int, default=256)
    parser.add_argument("--d-b", type=int, default=128)
    parser.add_argument("--rank", type=int, default=64)
    parser.add_argument("--steps", type=int, default=40)
    args = parser.parse_args(argv)
    train(args.fixture, args.out, d_a=args.d_a, d_b=args.d_b, r=args.rank, steps=args.steps)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
