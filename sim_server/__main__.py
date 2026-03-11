"""Entry point: python -m sim_server"""

import argparse

from sim_server.server import SimServer


def main():
    parser = argparse.ArgumentParser(description="TidyBot Sim Server")
    parser.add_argument("--task", default="BananaTestKitchen",
                        help="RoboCasa task / env name")
    parser.add_argument("--robot", default="TidyVerse",
                        help="Robot model name")
    parser.add_argument("--layout", type=int, default=1,
                        help="Kitchen layout ID")
    parser.add_argument("--style", type=int, default=1,
                        help="Kitchen style ID")
    parser.add_argument("--no-gui", action="store_true",
                        help="Run headless (no MuJoCo viewer)")
    parser.add_argument("--no-base-bridge", action="store_true",
                        help="Disable the base RPC bridge")
    parser.add_argument("--no-franka-bridge", action="store_true",
                        help="Disable the Franka arm bridge")
    parser.add_argument("--no-gripper-bridge", action="store_true",
                        help="Disable the gripper bridge")
    parser.add_argument("--no-camera-bridge", action="store_true",
                        help="Disable the camera bridge")
    parser.add_argument("--no-http-api", action="store_true",
                        help="Disable the HTTP control API bridge")
    parser.add_argument("--http-port", type=int, default=8081,
                        help="Port for the HTTP control API (default: 8081)")
    args = parser.parse_args()

    server = SimServer(
        task=args.task,
        robot=args.robot,
        layout=args.layout,
        style=args.style,
        has_renderer=not args.no_gui,
    )

    # Register bridges (imported from installed service packages)
    if not args.no_base_bridge:
        from base_server.server import BaseBridge
        server.add_bridge(BaseBridge(server))
    if not args.no_franka_bridge:
        from franka_server.server import FrankaBridge
        server.add_bridge(FrankaBridge(server))
    if not args.no_gripper_bridge:
        from gripper_server.server import GripperBridge
        server.add_bridge(GripperBridge(server))
    if not args.no_camera_bridge:
        from camera_server.server import CameraBridge
        server.add_bridge(CameraBridge(server))

    if not args.no_http_api:
        from sim_server.bridges.http_api import HttpApiBridge
        server.add_bridge(HttpApiBridge(server, port=args.http_port))

    server.run()


if __name__ == "__main__":
    main()
