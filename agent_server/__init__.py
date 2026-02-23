"""agent_server — simulated TidyBot agent server.

Call ``agent_server.init()`` to create the environment, then use::

    from robot_sdk import arm, base, gripper, sensors

exactly as you would on the real TidyBot hardware.
"""

import os
import sys


def setup_paths():
    """Fix sys.path so that the local robocasa/ and robosuite/ repos
    are importable (same trick as teleop_kitchen.py lines 23-30).

    Safe to call multiple times — only inserts paths once.
    """
    _project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for _repo in ("robocasa", "robosuite"):
        _repo_root = os.path.join(_project_root, _repo)
        if os.path.isdir(_repo_root) and _repo_root not in sys.path:
            sys.path.insert(0, _repo_root)

    # Also add the agent_server/ directory itself so that
    # ``from robot_sdk import arm`` works as a top-level import.
    _agent_server_dir = os.path.dirname(os.path.abspath(__file__))
    if _agent_server_dir not in sys.path:
        sys.path.insert(0, _agent_server_dir)


def init(task="Kitchen", robot="PandaOmron", layout=1, style=1, has_renderer=True, **kwargs):
    """Initialise the simulated robot environment.

    Args:
        task: RoboCasa task / env name.
        robot: Robot model name (e.g. "PandaOmron", "TidyVerse").
        layout: Kitchen layout ID.
        style: Kitchen style ID.
        has_renderer: Whether to open the MuJoCo viewer.
        **kwargs: Forwarded to ``robosuite.make()``.
    """
    setup_paths()

    # ----------------------------------------------------------------
    # Now that paths are set up, import and create the SimRobot.
    # ----------------------------------------------------------------
    from agent_server.sim_robot import SimRobot

    print(f"[agent_server] Initialising: task={task}, robot={robot}, layout={layout}, style={style}")
    robot = SimRobot(
        env_name=task,
        robot=robot,
        layout=layout,
        style=style,
        has_renderer=has_renderer,
        **kwargs,
    )

    # Register robot in BOTH module namespaces so get_robot() works
    # whether accessed as agent_server.robot_sdk._runtime or robot_sdk._runtime
    from agent_server.robot_sdk import _runtime as _rt_pkg
    _rt_pkg.set_robot(robot)
    # Also set on the top-level robot_sdk (imported from sys.path)
    from robot_sdk import _runtime as _rt_top
    _rt_top.set_robot(robot)
    print("[agent_server] Ready.")
    return robot
