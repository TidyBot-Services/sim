"""Gripper control — TidyBot-compatible API backed by SimRobot."""

from ._runtime import get_robot


def open(speed=None, force=None):
    """Fully open the gripper.

    Args:
        speed: Ignored in sim (binary gripper).
        force: Ignored in sim (binary gripper).
    """
    get_robot().gripper_open()


def close(speed=None, force=None):
    """Fully close the gripper.

    Args:
        speed: Ignored in sim (binary gripper).
        force: Ignored in sim (binary gripper).
    """
    get_robot().gripper_close()


def grasp(speed=None, force=None):
    """Close the gripper and return True if an object is grasped.

    Args:
        speed: Ignored in sim (binary gripper).
        force: Ignored in sim (binary gripper).
    """
    return get_robot().gripper_grasp()


def move(position, speed=None, force=None):
    """Move the gripper to a normalised position (0 = closed, 1 = open).

    Note: In simulation the gripper only supports binary open/close via
    the GRIP controller, so this snaps to the nearest state.

    Args:
        position: Target position (0 = closed, 1 = open).
        speed: Ignored in sim (binary gripper).
        force: Ignored in sim (binary gripper).
    """
    if position > 0.5:
        open()
    else:
        close()


def activate():
    """Activate the gripper. No-op in sim (gripper is always active)."""
    pass


def calibrate():
    """Calibrate the gripper. No-op in sim."""
    pass


def get_state():
    """Return a dict with the current gripper state."""
    robot = get_robot()
    return robot.get_gripper_state()
