from .base import BaseTracker, TrackResult, TrackState
from .sift_tracker import SiftTracker

__all__ = ["BaseTracker", "TrackResult", "TrackState", "SiftTracker"]

try:
    from .ai_tracker import AiTracker  # noqa: F401

    __all__.append("AiTracker")
except ImportError:
    # torch / kornia 没装就跳过，SIFT 仍可用
    pass
