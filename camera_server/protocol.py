"""Camera server protocol types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import numpy as np


@dataclass
class CameraInfo:
    """Info about a single camera."""
    device_id: str = ""
    name: str = ""
    serial: str = ""
    is_streaming: bool = False
    supported_streams: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "device_id": self.device_id,
            "name": self.name,
            "serial": self.serial,
            "is_streaming": self.is_streaming,
            "supported_streams": list(self.supported_streams),
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CameraInfo:
        return cls(
            device_id=d.get("device_id", ""),
            name=d.get("name", ""),
            serial=d.get("serial", ""),
            is_streaming=d.get("is_streaming", False),
            supported_streams=d.get("supported_streams", []),
        )


@dataclass
class CameraStateMsg:
    """State of the camera server."""
    cameras: List[CameraInfo] = field(default_factory=list)
    is_streaming: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {
            "cameras": [c.to_dict() for c in self.cameras],
            "is_streaming": self.is_streaming,
        }

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> CameraStateMsg:
        data = d.get("data", d)
        cameras = [CameraInfo.from_dict(c) for c in data.get("cameras", [])]
        return cls(
            cameras=cameras,
            is_streaming=data.get("is_streaming", False),
        )


@dataclass
class DecodedFrame:
    """A decoded camera frame."""
    device_id: str
    stream_type: str
    frame: np.ndarray
    timestamp: float
    width: int = 0
    height: int = 0
