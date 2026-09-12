"""NumPy port of the flybody DMPO flight policy (LayerNormMLP + mean head)."""
from __future__ import annotations

from pathlib import Path

import numpy as np

# Acme LayerNormMLP(256,256,256) + MultivariateNormalDiagHead, checkpoint order:
# Linear1.b, Linear1.w, LN.offset, LN.scale, Linear2.b/w, Linear3.b/w, mean.b/w, std.b/w
_VAR = "_variables/{i}/.ATTRIBUTES/VARIABLE_VALUE"


def _tensor(reader, i: int) -> np.ndarray:
    return np.asarray(reader.get_tensor(_VAR.format(i=i)), dtype=np.float32)


def load_weights(ckpt_dir: Path) -> dict[str, np.ndarray]:
    import tensorflow as tf

    prefix = str(Path(ckpt_dir) / "variables" / "variables")
    reader = tf.train.load_checkpoint(prefix)
    return {
        "w1": _tensor(reader, 1),
        "b1": _tensor(reader, 0),
        "ln_offset": _tensor(reader, 2),
        "ln_scale": _tensor(reader, 3),
        "w2": _tensor(reader, 5),
        "b2": _tensor(reader, 4),
        "w3": _tensor(reader, 7),
        "b3": _tensor(reader, 6),
        "w_mean": _tensor(reader, 9),
        "b_mean": _tensor(reader, 8),
    }


def concat_obs(observation: dict) -> np.ndarray:
    parts = [
        np.asarray(observation[k], dtype=np.float32).reshape(-1)
        for k in sorted(observation.keys())
    ]
    return np.concatenate(parts) if parts else np.zeros((0,), np.float32)


def _layer_norm(x: np.ndarray, scale: np.ndarray, offset: np.ndarray, eps=1e-5):
    mean = x.mean(axis=-1, keepdims=True)
    var = x.var(axis=-1, keepdims=True)
    return (x - mean) / np.sqrt(var + eps) * scale + offset


def _elu(x: np.ndarray) -> np.ndarray:
    return np.where(x > 0.0, x, np.exp(np.clip(x, -80.0, 0.0)) - 1.0)


class FlightPolicy:
    def __init__(self, ckpt_dir: Path):
        w = load_weights(ckpt_dir)
        self.w1, self.b1 = w["w1"], w["b1"]
        self.ln_scale, self.ln_offset = w["ln_scale"], w["ln_offset"]
        self.w2, self.b2 = w["w2"], w["b2"]
        self.w3, self.b3 = w["w3"], w["b3"]
        self.w_mean, self.b_mean = w["w_mean"], w["b_mean"]
        print(
            f"flight MLP {self.w1.shape[0]} -> {self.w1.shape[1]}³ -> {self.w_mean.shape[1]}",
            flush=True,
        )

    def __call__(self, observation: dict) -> np.ndarray:
        # Acme LayerNormMLP: Linear -> LN -> tanh -> MLP(elu, activate_final=True)
        x = concat_obs(observation)
        h = _layer_norm(x @ self.w1 + self.b1, self.ln_scale, self.ln_offset)
        h = np.tanh(h)
        h = _elu(h @ self.w2 + self.b2)
        h = _elu(h @ self.w3 + self.b3)
        mean = h @ self.w_mean + self.b_mean
        return np.clip(mean, -1.0, 1.0).astype(np.float32)
