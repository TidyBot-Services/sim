"""Run the camera server: python -m camera_server"""

import argparse

import uvicorn

from .config import CameraServerConfig
from .server import app, configure


def main():
    parser = argparse.ArgumentParser(description="Sim Camera Server")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=5581)
    parser.add_argument("--agent-url", default="http://localhost:8080",
                        help="Agent server base URL")
    parser.add_argument("--yolo-url", default="http://158.130.109.188:8010",
                        help="YOLO-E server URL")
    parser.add_argument("--fps", type=int, default=20,
                        help="Capture FPS from agent server")
    args = parser.parse_args()

    cfg = CameraServerConfig(
        host=args.host,
        port=args.port,
        agent_server_url=args.agent_url,
        yolo_server_url=args.yolo_url,
        capture_fps=args.fps,
    )
    configure(cfg)
    uvicorn.run(app, host=cfg.host, port=cfg.port)


if __name__ == "__main__":
    main()
