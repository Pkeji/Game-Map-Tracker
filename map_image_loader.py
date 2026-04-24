"""Shared helpers for loading large map images."""

from __future__ import annotations

import cv2
import numpy as np


def load_map_image(path: str, *, label: str) -> np.ndarray | None:
    """Load a map image through a shared entry point for future diagnostics."""
    _ = label
    return cv2.imread(path)
