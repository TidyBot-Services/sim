"""Sensor readings — TidyBot-compatible API backed by SimRobot."""

import warnings

import numpy as np
from ._runtime import get_robot


def get_arm_joints():
    """Return the 7-DOF arm joint positions as a numpy array."""
    return get_robot().get_arm_joints()


def get_ee_pose():
    """Return (position, orientation_matrix) of the end-effector in world frame."""
    return get_robot().get_ee_pose()


def get_ee_position():
    """Return the end-effector position as a 3-element numpy array."""
    return get_robot().get_ee_pose()[0]


def get_base_pose():
    """Return (position_xy_array, heading_radians) of the mobile base."""
    return get_robot().get_base_pose()


def get_gripper_position():
    """Return the mean gripper finger qpos (0 = closed, positive = open)."""
    state = get_robot().get_gripper_state()
    return state["position"]


def get_camera_frame(device_id="robot0_agentview_center", as_jpeg=False):
    """Return an RGB image (H, W, 3) uint8 from the named camera.

    Requires init with ``has_offscreen_renderer=True, use_camera_obs=True,
    camera_names=[...]``.

    Args:
        device_id: Camera name string.
        as_jpeg: If True, return JPEG-encoded bytes instead of numpy array.

    Available cameras on PandaOmron:
        robot0_agentview_center, robot0_agentview_left, robot0_agentview_right,
        robot0_frontview, robot0_robotview, robot0_eye_in_hand
    """
    frame = get_robot().get_camera_frame(device_id)
    if as_jpeg:
        import io
        from PIL import Image
        img = Image.fromarray(frame)
        buf = io.BytesIO()
        img.save(buf, format="JPEG")
        return buf.getvalue()
    return frame


def get_depth_frame(device_id="robot0_agentview_center"):
    """Return a depth image from the named camera.

    Not yet supported — requires offscreen renderer depth buffer configuration.
    Returns None with a warning.
    """
    warnings.warn(
        "get_depth_frame() not supported in sim — requires depth buffer configuration. Returning None.",
        stacklevel=2,
    )
    return None


def get_camera_intrinsics(device_id="robot0_agentview_center"):
    """Return camera intrinsic parameters as a dict.

    Reads field-of-view from the MuJoCo model and computes a pinhole camera
    intrinsics matrix. Returns None if the camera is not found.
    """
    robot = get_robot()
    sim = robot.sim
    # Try to find the camera in the MuJoCo model
    try:
        cam_id = sim.model.camera_name2id(device_id)
    except Exception:
        warnings.warn(
            f"Camera '{device_id}' not found in MuJoCo model. Returning None.",
            stacklevel=2,
        )
        return None

    fovy = sim.model.cam_fovy[cam_id]
    # Get image resolution from env config (default 256x256 for robosuite)
    height = robot.env.camera_heights[0] if hasattr(robot.env, "camera_heights") else 256
    width = robot.env.camera_widths[0] if hasattr(robot.env, "camera_widths") else 256

    # Compute focal length from vertical FoV
    fy = height / (2.0 * np.tan(np.radians(fovy) / 2.0))
    fx = fy  # Square pixels assumed
    cx = width / 2.0
    cy = height / 2.0

    return {
        "fx": fx,
        "fy": fy,
        "cx": cx,
        "cy": cy,
        "width": width,
        "height": height,
        "fovy": fovy,
    }


def get_arm_velocities():
    """Return the 7-DOF arm joint velocities as a numpy array."""
    return get_robot().get_arm_velocities()


def get_ee_wrench():
    """Return the end-effector wrench (force/torque) as a 6-element array.

    Not available in basic sim — returns zeros.
    """
    warnings.warn(
        "get_ee_wrench() not available in basic sim. Returning zeros.",
        stacklevel=2,
    )
    return np.zeros(6)


def get_gripper_width():
    """Return the gripper opening width computed from finger joint positions."""
    return get_robot().get_gripper_width()


def get_all_state():
    """Return a dict with all sensor readings."""
    robot = get_robot()
    ee_pos, ee_ori = robot.get_ee_pose()
    base_pos, base_yaw = robot.get_base_pose()
    return {
        "ee_pos": ee_pos.tolist(),
        "ee_ori": ee_ori.tolist(),
        "arm_joints": robot.get_arm_joints().tolist(),
        "base_pos": base_pos.tolist(),
        "base_heading": base_yaw,
        "gripper": robot.get_gripper_state(),
    }
