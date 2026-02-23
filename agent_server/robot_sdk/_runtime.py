"""Singleton reference to the active SimRobot instance."""

import threading

_sim_robot = None
_thread_local = threading.local()


def get_robot():
    """Return the active SimRobot (or thread-local proxy) instance."""
    # Thread-local override first (ZMQ proxy in executor thread)
    robot = getattr(_thread_local, '_sim_robot', None)
    if robot is not None:
        return robot
    # Global fallback (real SimRobot on main thread)
    if _sim_robot is None:
        raise RuntimeError(
            "SimRobot not initialised. Call agent_server.init() first."
        )
    return _sim_robot


def set_robot(robot):
    """Register the active SimRobot instance."""
    global _sim_robot
    _sim_robot = robot


def set_thread_robot(robot):
    """Set a thread-local robot override (e.g. ZmqRobotProxy)."""
    _thread_local._sim_robot = robot


def clear_thread_robot():
    """Remove the thread-local robot override."""
    _thread_local._sim_robot = None
