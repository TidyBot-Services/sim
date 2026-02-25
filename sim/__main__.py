"""Entry point: python -m sim"""

import argparse

from sim.server import SimServer


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
    args = parser.parse_args()

    server = SimServer(
        task=args.task,
        robot=args.robot,
        layout=args.layout,
        style=args.style,
        has_renderer=not args.no_gui,
    )

    # Register bridges
    if not args.no_base_bridge:
        from sim.bridges.base import BaseBridge
        server.add_bridge(BaseBridge(server))
    if not args.no_franka_bridge:
        from sim.bridges.franka import FrankaBridge
        server.add_bridge(FrankaBridge(server))
    if not args.no_gripper_bridge:
        from sim.bridges.gripper import GripperBridge
        server.add_bridge(GripperBridge(server))
    if not args.no_camera_bridge:
        from sim.bridges.camera import CameraBridge
        server.add_bridge(CameraBridge(server))

    server.run()


if __name__ == "__main__":
    main()
