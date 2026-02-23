"""Rewind / trajectory replay — TidyBot-compatible API (sim stubs).

The real rewind module records and replays robot trajectories in reverse for
recovery. In sim, most operations are no-ops; recovery falls back to go_home.
"""

import warnings

from ._runtime import get_robot


def get_status():
    """Return the current rewind buffer status."""
    return {"enabled": False, "steps": 0}


def rewind_steps(n):
    """Rewind the last *n* trajectory steps. No-op in sim."""
    warnings.warn(
        f"rewind_steps({n}) not supported in sim — trajectory recording not available.",
        stacklevel=2,
    )


def rewind_percentage(pct):
    """Rewind a percentage of the recorded trajectory. No-op in sim."""
    warnings.warn(
        f"rewind_percentage({pct}) not supported in sim — trajectory recording not available.",
        stacklevel=2,
    )


def rewind_to_safe():
    """Rewind to a safe configuration. In sim, moves the arm home."""
    from . import arm
    arm.go_home()


def reset_to_home():
    """Reset the robot to its home configuration (arm + base)."""
    from . import arm, base
    arm.go_home()
    # Reset base to origin
    base.move_to_pose(0.0, 0.0, 0.0)


def clear_trajectory():
    """Clear the recorded trajectory buffer. No-op in sim."""
    pass
