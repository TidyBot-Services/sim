"""Tolerances, gains, and timeouts for simulated robot control."""

from dataclasses import dataclass, field


@dataclass
class LeaseConfig:
    idle_timeout_s: float = 120.0    # revoke after 2 min idle
    max_duration_s: float = 600.0    # hard cap 10 min
    check_interval_s: float = 2.0
    reset_on_release: bool = True    # reset scene when lease ends


@dataclass
class ServerConfig:
    host: str = "0.0.0.0"
    port: int = 8080
    task: str = "BananaTestKitchen"
    robot: str = "TidyVerse"
    layout: int = 1
    style: int = 1
    lease: LeaseConfig = field(default_factory=LeaseConfig)

# Arm (EE) convergence tolerances
ARM_POS_TOL = 0.01  # metres
ARM_ORI_TOL = 0.05  # radians

# Base convergence tolerances
BASE_POS_TOL = 0.05  # metres
BASE_ORI_TOL = 0.1   # radians

# Maximum steps before timeout
ARM_MAX_STEPS = 300
BASE_MAX_STEPS = 500
GRIPPER_STEPS = 10

# Control frequency (must match env)
CONTROL_FREQ = 20

# OSC output ranges (from default_pandaomron.json)
ARM_OUTPUT_MAX_POS = 0.05   # metres per step
ARM_OUTPUT_MAX_ORI = 0.5    # radians per step
