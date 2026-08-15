import numpy as np

from chat_compressor.translate.adapter import GatedMLPAdapter


def test_p2_forward_shape() -> None:
    adapter = GatedMLPAdapter(d_a=256, d_b=128, r=32)
    rng = np.random.default_rng(1)
    c_a = rng.normal(size=(5, 256)).astype(np.float32)
    c_b = adapter.forward(c_a)
    assert c_b.shape == (5, 128)
    assert c_b.dtype == np.float32
