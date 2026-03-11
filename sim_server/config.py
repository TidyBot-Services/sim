"""Tolerances, gains, and timeouts for simulated robot control."""

# Arm (EE) convergence tolerances
ARM_POS_TOL = 0.05  # metres
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

# Cartesian impedance gains (matching real Franka defaults)
# Real robot runs at 1kHz; sim at 20Hz — gains scaled down for stability.
K_CART = [375.0, 375.0, 375.0, 25.0, 25.0, 25.0]  # stiffness [N/m, N/m, N/m, Nm/rad, Nm/rad, Nm/rad]
D_CART = [38.7, 38.7, 38.7, 10.0, 10.0, 10.0]      # damping   [N·s/m, ..., Nm·s/rad, ...]

# Joint-space impedance gains (matching real Franka joint impedance)
# Real robot: K ~ [600,600,600,600,250,150,50] at 1kHz; scaled ~4x down for 20Hz sim.
K_JOINT = [150.0, 150.0, 150.0, 150.0, 60.0, 40.0, 15.0]  # Nm/rad
D_JOINT = [30.0, 30.0, 30.0, 30.0, 12.0, 8.0, 3.0]         # Nm·s/rad
