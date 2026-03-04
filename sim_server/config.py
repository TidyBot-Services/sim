"""Tolerances, gains, and timeouts for simulated robot control."""

# Arm (EE) convergence tolerances
ARM_POS_TOL = 0.05  # metres (relaxed for sim — OSC struggles near fixtures)
ARM_ORI_TOL = 0.05  # radians

# Base convergence tolerances
BASE_POS_TOL = 0.05  # metres
BASE_ORI_TOL = 0.1   # radians

# Maximum steps before timeout
ARM_MAX_STEPS = 600
BASE_MAX_STEPS = 500
GRIPPER_STEPS = 10

# Control frequency (must match env)
CONTROL_FREQ = 20

# OSC output ranges (from default_pandaomron.json)
ARM_OUTPUT_MAX_POS = 0.05   # metres per step
ARM_OUTPUT_MAX_ORI = 0.2    # radians per step (reduced to prevent orientation overshoot)
