"""Small MLP autoencoder (torch, CPU) on windowed features; score = reconstruction MSE."""

from __future__ import annotations

import numpy as np
import torch
from torch import nn

from ml.models.base import Detector, as_array


class AEDetector(Detector):
    name = "ae"
    input_kind = "features"

    def __init__(self, hidden: int = 64, bottleneck: int = 8, epochs: int = 20, seed: int = 0):
        super().__init__()
        self.hidden, self.bottleneck, self.epochs, self.seed = hidden, bottleneck, epochs, seed
        self.net: nn.Module | None = None
        self.mu: np.ndarray | None = None
        self.sd: np.ndarray | None = None

    def _scale(self, X) -> torch.Tensor:
        return torch.from_numpy(((as_array(X) - self.mu) / self.sd).astype(np.float32))

    def _fit(self, X) -> None:
        torch.manual_seed(self.seed)
        A = as_array(X)
        self.mu = A.mean(axis=0)
        self.sd = A.std(axis=0) + 1e-6
        d = A.shape[1]
        self.net = nn.Sequential(
            nn.Linear(d, self.hidden),
            nn.ReLU(),
            nn.Linear(self.hidden, self.bottleneck),
            nn.ReLU(),
            nn.Linear(self.bottleneck, self.hidden),
            nn.ReLU(),
            nn.Linear(self.hidden, d),
        )
        data = self._scale(A)
        opt = torch.optim.Adam(self.net.parameters(), lr=1e-3)
        gen = torch.Generator().manual_seed(self.seed)
        for _ in range(self.epochs):
            for idx in torch.randperm(len(data), generator=gen).split(256):
                batch = data[idx]
                opt.zero_grad()
                loss = nn.functional.mse_loss(self.net(batch), batch)
                loss.backward()
                opt.step()

    def raw_score(self, X) -> np.ndarray:
        if self.net is None:
            raise RuntimeError("fit() first")
        with torch.no_grad():
            x = self._scale(X)
            return ((self.net(x) - x) ** 2).mean(dim=1).numpy().astype(float)
