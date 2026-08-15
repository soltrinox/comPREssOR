"""Pattern 2 — gated MLP adapter: C_B = MLP_psi(Encoder_phi(C_A))."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


def _gelu(x: np.ndarray) -> np.ndarray:
    return 0.5 * x * (1.0 + np.tanh(np.sqrt(2.0 / np.pi) * (x + 0.044715 * x**3)))


def _sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -40.0, 40.0)))


@dataclass
class GatedMLPAdapter:
    """Numpy gated-MLP so pytest needs no torch. Train script may wrap the same weights."""

    d_a: int
    d_b: int
    r: int = 64
    w1: np.ndarray | None = None
    b1: np.ndarray | None = None
    w_g: np.ndarray | None = None
    b_g: np.ndarray | None = None
    w2: np.ndarray | None = None
    b2: np.ndarray | None = None
    w3: np.ndarray | None = None
    b3: np.ndarray | None = None

    def __post_init__(self) -> None:
        rng = np.random.default_rng(0)
        if self.w1 is None:
            self.w1 = (rng.normal(0, 0.05, (self.d_a, self.r))).astype(np.float32)
            self.b1 = np.zeros((self.r,), dtype=np.float32)
            self.w_g = (rng.normal(0, 0.05, (self.r, self.r))).astype(np.float32)
            self.b_g = np.zeros((self.r,), dtype=np.float32)
            self.w2 = (rng.normal(0, 0.05, (self.r, self.r))).astype(np.float32)
            self.b2 = np.zeros((self.r,), dtype=np.float32)
            self.w3 = (rng.normal(0, 0.05, (self.r, self.d_b))).astype(np.float32)
            self.b3 = np.zeros((self.d_b,), dtype=np.float32)

    def forward(self, c_a: np.ndarray) -> np.ndarray:
        x = np.asarray(c_a, dtype=np.float32)
        h = _gelu(x @ self.w1 + self.b1)
        g = _sigmoid(h @ self.w_g + self.b_g)
        z = _gelu((h * g) @ self.w2 + self.b2)
        out = z @ self.w3 + self.b3
        return out.astype(np.float32)

    def state_dict(self) -> dict[str, np.ndarray]:
        return {
            "w1": self.w1,
            "b1": self.b1,
            "w_g": self.w_g,
            "b_g": self.b_g,
            "w2": self.w2,
            "b2": self.b2,
            "w3": self.w3,
            "b3": self.b3,
            "d_a": np.array([self.d_a]),
            "d_b": np.array([self.d_b]),
            "r": np.array([self.r]),
        }

    @classmethod
    def from_state_dict(cls, data: dict[str, np.ndarray]) -> GatedMLPAdapter:
        return cls(
            d_a=int(data["d_a"].reshape(-1)[0]),
            d_b=int(data["d_b"].reshape(-1)[0]),
            r=int(data["r"].reshape(-1)[0]),
            w1=data["w1"],
            b1=data["b1"],
            w_g=data["w_g"],
            b_g=data["b_g"],
            w2=data["w2"],
            b2=data["b2"],
            w3=data["w3"],
            b3=data["b3"],
        )

    def save(self, path: str | Path) -> Path:
        dest = Path(path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        np.savez(dest, **self.state_dict())
        return dest

    @classmethod
    def load(cls, path: str | Path) -> GatedMLPAdapter:
        loaded = np.load(path, allow_pickle=False)
        return cls.from_state_dict({k: loaded[k] for k in loaded.files})

    def train_step(
        self,
        c_a: np.ndarray,
        c_b: np.ndarray,
        lr: float = 1e-2,
        lam: float = 0.1,
    ) -> float:
        """One SGD step: L2 + lambda * (1 - cosine). Finite-diff-free analytic on last layer."""
        pred = self.forward(c_a)
        target = np.asarray(c_b, dtype=np.float32)
        diff = pred - target
        l2 = float((diff**2).mean())
        pn = pred / np.maximum(np.linalg.norm(pred, axis=-1, keepdims=True), 1e-8)
        tn = target / np.maximum(np.linalg.norm(target, axis=-1, keepdims=True), 1e-8)
        cosine = float((pn * tn).sum(axis=-1).mean())
        loss = l2 + lam * (1.0 - cosine)
        # last-layer gradient
        grad_out = (2.0 * diff) / max(diff.size, 1)
        x = np.asarray(c_a, dtype=np.float32)
        h = _gelu(x @ self.w1 + self.b1)
        g = _sigmoid(h @ self.w_g + self.b_g)
        z = _gelu((h * g) @ self.w2 + self.b2)
        self.w3 = self.w3 - lr * (z.T @ grad_out)
        self.b3 = self.b3 - lr * grad_out.sum(axis=0)
        return loss
