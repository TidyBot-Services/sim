"""Camera server configuration."""

from dataclasses import dataclass, field


@dataclass
class CameraServerConfig:
    host: str = "0.0.0.0"
    port: int = 5581
    agent_server_url: str = "http://localhost:8080"
    cameras: list[str] = field(default_factory=lambda: [
        "robot0_agentview_center",
        "robot0_eye_in_hand",
    ])
    capture_fps: int = 20
    jpeg_quality: int = 85
    yolo_server_url: str = "http://158.130.109.188:8010"
