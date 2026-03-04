"""SimRobot — wraps a robosuite PandaOmron environment and exposes
blocking high-level control methods consumed by the robot_sdk modules."""

import json
import os

import numpy as np
import robocasa  # noqa: F401 — registers Kitchen env with robosuite
import robosuite
import robosuite.utils.transform_utils as T
from robosuite.utils.control_utils import orientation_error
from robosuite.controllers import load_composite_controller_config

from sim_server.config import (
    ARM_MAX_STEPS,
    ARM_ORI_TOL,
    ARM_OUTPUT_MAX_ORI,
    ARM_OUTPUT_MAX_POS,
    ARM_POS_TOL,
    BASE_MAX_STEPS,
    BASE_ORI_TOL,
    BASE_POS_TOL,
    CONTROL_FREQ,
    GRIPPER_STEPS,
)


# Constant correction rotation: Rz(+90°) aligns MuJoCo EE site frame
# with real Franka O_T_EE convention (DH-based forward kinematics).
# Without this, EE X/Y axes are swapped between sim and real robot,
# causing dpitch/droll/dyaw to rotate around wrong physical axes.
_EE_FRAME_CORRECTION = np.array([
    [0.0, -1.0, 0.0],
    [1.0,  0.0, 0.0],
    [0.0,  0.0, 1.0],
])  # Rz(+90°)
_EE_FRAME_CORRECTION_INV = _EE_FRAME_CORRECTION.T  # Rz(-90°)


class SimRobot:
    """Blocking control wrapper around a robosuite PandaOmron environment."""

    def __init__(
        self,
        env_name="Kitchen",
        robot="PandaOmron",
        layout=1,
        style=1,
        has_renderer=True,
        has_offscreen_renderer=False,
        use_camera_obs=False,
        **env_kwargs,
    ):
        robot_name = robot
        controller_config = load_composite_controller_config(robot=robot_name)

        self.env = robosuite.make(
            env_name=env_name,
            robots=robot_name,
            controller_configs=controller_config,
            translucent_robot=False,
            has_renderer=has_renderer,
            has_offscreen_renderer=has_offscreen_renderer,
            render_camera=None,
            ignore_done=True,
            use_camera_obs=use_camera_obs,
            control_freq=CONTROL_FREQ,
            renderer="mjviewer",
            obj_registries=("aigen",),
            **env_kwargs,
        )

        # Pin the layout and style, then reset
        self.env.layout_and_style_ids = [[layout, style]]
        self._last_obs = self.env.reset()

        # Cache robot reference
        self.robot = self.env.robots[0]
        self.sim = self.env.sim

        # Fix camera positions for TidyVerse
        if robot_name == "TidyVerse":
            self._fix_tidyverse_cameras()
        self._arm = self.robot.arms[0]  # "right"

        # Store the EE site id for fast lookup
        self._eef_site_id = self.robot.eef_site_id[self._arm]

        # Store base site name for reading base pose
        self._base_site_name = self.robot.robot_model.base.correct_naming("center")
        self._base_site_id = self.sim.model.site_name2id(self._base_site_name)

        # Move arm to real-robot home joints so EE frame convention matches.
        # robosuite's init_qpos differs from the real Franka home, which would
        # cause EE-frame operations (dpitch, etc.) to rotate around wrong axes.
        SDK_HOME = np.array([0.0, -0.785, 0.0, -2.356, 0.0, 1.913, 0.785])
        for i, idx in enumerate(self.robot._ref_joint_pos_indexes):
            self.sim.data.qpos[idx] = SDK_HOME[i]
        self.sim.forward()
        self._home_qpos = SDK_HOME.copy()
        self._joint_offset = np.zeros(7)  # no offset needed — sim matches real

        # OSC output maxima — used to normalise delta commands to [-1, 1]
        self._output_max = np.array([
            ARM_OUTPUT_MAX_POS, ARM_OUTPUT_MAX_POS, ARM_OUTPUT_MAX_POS,
            ARM_OUTPUT_MAX_ORI, ARM_OUTPUT_MAX_ORI, ARM_OUTPUT_MAX_ORI,
        ])

        # Load saved viewer camera if available (must be before gripper_open
        # which calls _step → _maybe_apply_pending_cam)
        self._viewer_cam_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "viewer_cam.json"
        )
        self._apply_saved_viewer_cam()

        # Open the gripper at start (matches go_home behaviour)
        self._gripper_closed = False
        self.gripper_open()

    def _apply_saved_viewer_cam(self):
        """Load saved viewer camera config to apply on first render."""
        self._pending_viewer_cam = None
        if not os.path.isfile(self._viewer_cam_path):
            return
        try:
            with open(self._viewer_cam_path) as f:
                self._pending_viewer_cam = json.load(f)
            print(f"[sim] Will apply saved viewer camera on first render")
        except Exception as e:
            print(f"[sim] Failed to load viewer camera: {e}")

    def _maybe_apply_pending_cam(self):
        """Apply pending camera config to the viewer if it exists."""
        if self._pending_viewer_cam is None:
            return
        viewer = getattr(self.env, "viewer", None)
        if viewer is None or viewer.viewer is None:
            return
        v = viewer.viewer
        cfg = self._pending_viewer_cam
        v.cam.lookat = cfg["lookat"]
        v.cam.distance = cfg["distance"]
        v.cam.azimuth = cfg["azimuth"]
        v.cam.elevation = cfg["elevation"]
        print(f"[sim] Applied saved viewer camera")
        self._pending_viewer_cam = None  # only apply once

    def save_viewer_cam(self):
        """Save current viewer camera position to disk."""
        viewer = getattr(self.env, "viewer", None)
        if viewer is None:
            return {"error": "no viewer"}
        v = viewer.viewer
        if v is None:
            return {"error": "viewer not initialized"}
        cam_cfg = {
            "lookat": list(float(x) for x in v.cam.lookat),
            "distance": float(v.cam.distance),
            "azimuth": float(v.cam.azimuth),
            "elevation": float(v.cam.elevation),
        }
        with open(self._viewer_cam_path, "w") as f:
            json.dump(cam_cfg, f, indent=2)
        print(f"[sim] Saved viewer camera to {self._viewer_cam_path}")
        return cam_cfg

    def _fix_tidyverse_cameras(self):
        """Reposition cameras for TidyVerse robot geometry.

        Robocasa's Kitchen._postprocess_model overwrites camera positions
        from CAM_CONFIGS at model compile time. Since we don't patch robocasa,
        we fix the compiled MuJoCo model directly after env.reset().
        """
        import mujoco
        model = self.sim.model._model

        cam_overrides = {
            # Wrist camera: offset for longer gripper coupling adapter
            "robot0_eye_in_hand": {"pos": [-0.05, 0, 0.27], "fovy": 42.5},
            # Base camera: mounted on mast at front-left of base,
            # looking forward and slightly down toward the workspace.
            # Coordinates are relative to mobilebase0_support body
            # (which is at the arm mount: 0.435, 0.254, 0.47225 from base center).
            # Base camera: front edge of base, centered, base-top height,
            # looking forward (+X). MuJoCo camera looks along -Z by default;
            # rotate -90 around Y to face +X: quat [w,x,y,z] = [0.707,0,-0.707,0]
            "robot0_agentview_center": {
                "pos": [0.17, 0.0, 0.0],
                "quat": [0.5, 0.5, -0.5, -0.5],
            },
        }

        for cam_name, overrides in cam_overrides.items():
            cam_id = mujoco.mj_name2id(
                model, mujoco.mjtObj.mjOBJ_CAMERA, cam_name
            )
            if cam_id < 0:
                continue
            if "pos" in overrides:
                model.cam_pos[cam_id] = overrides["pos"]
            if "quat" in overrides:
                model.cam_quat[cam_id] = overrides["quat"]
            if "fovy" in overrides:
                model.cam_fovy[cam_id] = overrides["fovy"]
            print(f"[sim_robot] Fixed {cam_name} camera")

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _step(self, action_dict):
        """Build the flat action vector and step the environment once."""
        action = self.robot.create_action_vector(action_dict)
        self._last_obs, _, _, _ = self.env.step(action)
        if self.env.has_renderer:
            self.env.render()
            self._maybe_apply_pending_cam()
        return self._last_obs

    def _zero_action_dict(self, base_mode=-1):
        """Return an action dict that commands zero motion everywhere."""
        return {
            self._arm: np.zeros(6),
            f"{self._arm}_gripper": np.array([1.0 if self._gripper_closed else -1.0]),
            "base": np.zeros(3),
            "base_mode": np.array([base_mode]),
            "torso": np.zeros(1),
        }

    # ------------------------------------------------------------------
    # State readers
    # ------------------------------------------------------------------

    def get_ee_pose(self):
        """Return (pos[3], ori_mat[3,3]) of the EE grip site in world frame."""
        pos = np.array(self.sim.data.site_xpos[self._eef_site_id]).copy()
        ori = self.sim.data.site_xmat[self._eef_site_id].reshape(3, 3).copy()
        return pos, ori

    def get_ee_pose_in_base_frame(self):
        """Return (pos[3], ori_mat[3,3]) of the EE in the robot base frame.

        Matches the real Franka's O_T_EE convention where O = base origin.
        """
        T_wb = self._get_base_transform()
        T_bw = T.pose_inv(T_wb)

        ee_pos_world = np.array(self.sim.data.site_xpos[self._eef_site_id])
        ee_ori_world = self.sim.data.site_xmat[self._eef_site_id].reshape(3, 3)

        # Build world-frame EE transform
        T_we = np.eye(4)
        T_we[:3, :3] = ee_ori_world
        T_we[:3, 3] = ee_pos_world

        # EE in base frame, with Rz(+90°) correction to match real Franka
        T_be = T_bw @ T_we
        R_corrected = T_be[:3, :3] @ _EE_FRAME_CORRECTION
        return T_be[:3, 3].copy(), R_corrected.copy()

    def get_arm_joints(self):
        """Return the 7-DOF arm joint positions."""
        return np.array([
            self.sim.data.qpos[i]
            for i in self.robot._ref_joint_pos_indexes
        ])

    def get_base_pose(self):
        """Return (xy_pos[2], yaw_radians) in world frame."""
        pos = np.array(self.sim.data.site_xpos[self._base_site_id]).copy()
        mat = self.sim.data.site_xmat[self._base_site_id].reshape(3, 3)
        yaw = np.arctan2(mat[1, 0], mat[0, 0])
        return pos[:2], float(yaw)

    def get_gripper_state(self):
        """Return a dict describing the gripper."""
        qpos = np.array([
            self.sim.data.qpos[i]
            for i in self.robot._ref_gripper_joint_pos_indexes[self._arm]
        ])
        return {
            "qpos": qpos.tolist(),
            "position": float(np.mean(np.abs(qpos))),
            "closed": self._gripper_closed,
        }

    def get_arm_velocities(self):
        """Return the 7-DOF arm joint velocities as a numpy array."""
        return np.array([
            self.sim.data.qvel[i]
            for i in self.robot._ref_joint_vel_indexes
        ])

    def get_gripper_width(self):
        """Return the gripper opening width from finger joint positions."""
        qpos = np.array([
            self.sim.data.qpos[i]
            for i in self.robot._ref_gripper_joint_pos_indexes[self._arm]
        ])
        return float(np.sum(np.abs(qpos)))

    def get_camera_frame(self, name="robot0_agentview_center"):
        """Return an RGB image from the named camera."""
        if not self.env.has_offscreen_renderer:
            raise RuntimeError(
                "Offscreen renderer not enabled. "
                "Pass has_offscreen_renderer=True and use_camera_obs=True to init()."
            )
        obs_key = f"{name}_image"
        if obs_key in self._last_obs:
            return self._last_obs[obs_key]
        raise KeyError(f"Camera '{name}' not found in observations. Available: {list(self._last_obs.keys())}")

    def render_camera_jpeg(self, name="robot0_agentview_center", width=256, height=256, quality=85):
        """Render a JPEG frame from the named camera using MuJoCo's native renderer.

        Works without offscreen rendering enabled — uses mujoco.Renderer directly.
        """
        import io
        import mujoco
        from PIL import Image

        model = self.sim.model._model
        data = self.sim.data._data

        if not hasattr(self, '_renderers'):
            self._renderers = {}

        key = (name, width, height)
        if key not in self._renderers:
            self._renderers[key] = mujoco.Renderer(model, height, width)

        renderer = self._renderers[key]
        opt = mujoco.MjvOption()
        opt.geomgroup[0] = False       # hide collision geoms
        opt.sitegroup[:] = [False] * 6  # hide sites

        renderer.update_scene(data, camera=name, scene_option=opt)
        frame = renderer.render().copy()

        buf = io.BytesIO()
        Image.fromarray(frame).save(buf, format="JPEG", quality=quality)
        return buf.getvalue()

    def render_camera_depth(self, name="robot0_agentview_center", width=256, height=256):
        """Render a depth frame from the named camera as 16-bit PNG bytes (mm)."""
        import mujoco
        import cv2

        model = self.sim.model._model
        data = self.sim.data._data

        if not hasattr(self, '_depth_renderers'):
            self._depth_renderers = {}

        key = (name, width, height)
        if key not in self._depth_renderers:
            self._depth_renderers[key] = mujoco.Renderer(model, height, width)
            self._depth_renderers[key].enable_depth_rendering()

        renderer = self._depth_renderers[key]
        opt = mujoco.MjvOption()
        opt.geomgroup[0] = False       # hide collision geoms
        opt.sitegroup[:] = [False] * 6  # hide sites

        renderer.update_scene(data, camera=name, scene_option=opt)
        depth_buf = renderer.render().copy()  # float32, normalized [0, 1]

        # Convert from normalized depth to linear meters using znear/zfar
        cam_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, name)
        extent = model.stat.extent
        znear = model.vis.map.znear * extent
        zfar = model.vis.map.zfar * extent
        # Linearize: depth_linear = znear * zfar / (zfar - depth_buf * (zfar - znear))
        depth_linear = znear * zfar / (zfar - depth_buf * (zfar - znear))
        # Clamp to zfar (background)
        depth_linear[depth_buf >= 1.0] = 0  # 0 = invalid/no return

        # Convert to uint16 millimeters for PNG encoding
        depth_mm = (depth_linear * 1000).astype(np.uint16)
        _, png_buf = cv2.imencode(".png", depth_mm)
        return png_buf.tobytes()

    # ------------------------------------------------------------------
    # Coordinate frame helpers
    # ------------------------------------------------------------------

    def _get_base_transform(self):
        """Return the 4x4 world-to-base transformation matrix."""
        pos = np.array(self.sim.data.site_xpos[self._base_site_id])
        mat = self.sim.data.site_xmat[self._base_site_id].reshape(3, 3)
        T_wb = np.eye(4)
        T_wb[:3, :3] = mat
        T_wb[:3, 3] = pos
        return T_wb

    def _world_pos_to_base_frame(self, world_pos):
        """Transform a position vector from world frame to base frame."""
        T_wb = self._get_base_transform()
        T_bw = T.pose_inv(T_wb)
        p_world = np.ones(4)
        p_world[:3] = world_pos
        return (T_bw @ p_world)[:3]

    def _world_ori_error_to_base_frame(self, ori_error_axisangle):
        """Rotate an axis-angle orientation error from world to base frame."""
        T_wb = self._get_base_transform()
        R_bw = T_wb[:3, :3].T  # inverse rotation
        return R_bw @ ori_error_axisangle

    # ------------------------------------------------------------------
    # Blocking arm control
    # ------------------------------------------------------------------

    def track_ee_pose_step(self, target_pos, target_ori_mat):
        """One physics step tracking a target EE pose in base frame.

        Targets are in the robot's base frame (matching real Franka O_T_EE).
        Converts to world frame internally for error computation, then sends
        base-frame deltas to the OSC controller.
        """
        target_pos = np.asarray(target_pos).flatten()[:3]
        target_ori_mat = np.asarray(target_ori_mat).reshape(3, 3)

        # Undo EE frame correction: Franka convention → MuJoCo site frame
        target_ori_mj = target_ori_mat @ _EE_FRAME_CORRECTION_INV

        # Convert base-frame target to world frame
        T_wb = self._get_base_transform()
        target_world_pos = T_wb[:3, :3] @ target_pos + T_wb[:3, 3]
        target_world_ori = T_wb[:3, :3] @ target_ori_mj

        cur_pos, cur_ori = self.get_ee_pose()

        pos_error_world = target_world_pos - cur_pos
        ori_error_world = orientation_error(target_world_ori, cur_ori)

        pos_error_base = self._world_pos_to_base_frame(cur_pos + pos_error_world) - \
                         self._world_pos_to_base_frame(cur_pos)
        ori_error_base = self._world_ori_error_to_base_frame(ori_error_world)

        delta = np.concatenate([pos_error_base, ori_error_base])
        norm_delta = np.clip(delta / self._output_max, -1.0, 1.0)

        ad = self._zero_action_dict(base_mode=-1)
        ad[self._arm] = norm_delta
        self._step(ad)

    def joint_positions_to_ee_pose(self, q):
        """FK: given 7 joint positions, return (pos, ori_mat) of the EE in base frame.

        Temporarily sets qpos, calls forward, reads site, restores state.
        Returns base-frame pose to match the real Franka O_T_EE convention.
        """
        saved_qpos = self.sim.data.qpos.copy()
        saved_qvel = self.sim.data.qvel.copy()

        for i, idx in enumerate(self.robot._ref_joint_pos_indexes):
            self.sim.data.qpos[idx] = q[i]
        self.sim.forward()

        ee_pos_world = np.array(self.sim.data.site_xpos[self._eef_site_id])
        ee_ori_world = self.sim.data.site_xmat[self._eef_site_id].reshape(3, 3)

        # Convert to base frame
        T_wb = self._get_base_transform()
        T_bw = T.pose_inv(T_wb)
        T_we = np.eye(4)
        T_we[:3, :3] = ee_ori_world
        T_we[:3, 3] = ee_pos_world
        T_be = T_bw @ T_we

        pos = T_be[:3, 3].copy()
        ori = (T_be[:3, :3] @ _EE_FRAME_CORRECTION).copy()

        self.sim.data.qpos[:] = saved_qpos
        self.sim.data.qvel[:] = saved_qvel
        self.sim.forward()

        return pos, ori

    def move_ee_to_pose(self, target_pos, target_ori_mat):
        """Blocking loop: move the EE to a target world-frame pose.

        Sends normalised delta actions to the OSC_POSE controller each step
        until convergence or timeout.
        """
        for _ in range(ARM_MAX_STEPS):
            cur_pos, cur_ori = self.get_ee_pose()

            # Position error in world frame
            pos_error_world = target_pos - cur_pos

            # Orientation error as axis-angle in world frame
            ori_error_world = orientation_error(target_ori_mat, cur_ori)

            # Check convergence
            pos_err_mag = np.linalg.norm(pos_error_world)
            ori_err_mag = np.linalg.norm(ori_error_world)
            if pos_err_mag < ARM_POS_TOL and ori_err_mag < ARM_ORI_TOL:
                break

            # Transform errors to base frame (OSC uses input_ref_frame="base")
            pos_error_base = self._world_pos_to_base_frame(cur_pos + pos_error_world) - \
                             self._world_pos_to_base_frame(cur_pos)
            ori_error_base = self._world_ori_error_to_base_frame(ori_error_world)

            # Normalise to [-1, 1] for the controller
            delta = np.concatenate([pos_error_base, ori_error_base])
            norm_delta = np.clip(delta / self._output_max, -1.0, 1.0)

            ad = self._zero_action_dict(base_mode=-1)
            ad[self._arm] = norm_delta
            self._step(ad)

    def move_ee_delta(self, dx=0.0, dy=0.0, dz=0.0, droll=0.0, dpitch=0.0, dyaw=0.0, frame="base"):
        """Move the EE by a delta in the specified frame.

        Args:
            dx, dy, dz: Position delta in metres.
            droll, dpitch, dyaw: Orientation delta in radians (applied as RPY).
            frame: "base" (robot base frame) or "ee" (end-effector frame).
        """
        if frame not in ("base", "ee"):
            raise ValueError(f"Invalid frame: {frame!r}. Must be 'base' or 'ee'")

        cur_pos, cur_ori = self.get_ee_pose()
        delta_pos = np.array([dx, dy, dz])

        if frame == "base":
            # Delta is in base frame — rotate to world frame
            T_wb = self._get_base_transform()
            R_wb = T_wb[:3, :3]
            world_delta = R_wb @ delta_pos
        else:  # frame == "ee"
            # Delta is in EE frame — rotate to world frame
            world_delta = cur_ori @ delta_pos

        target_pos = cur_pos + world_delta

        # Compose orientation delta
        if droll != 0.0 or dpitch != 0.0 or dyaw != 0.0:
            delta_rot = T.euler2mat(np.array([droll, dpitch, dyaw]))
            if frame == "ee":
                # R_target = R_current @ R_delta
                target_ori = cur_ori @ delta_rot
            else:
                # R_target = R_base_world @ R_delta @ R_base_world^T @ R_current
                # i.e. rotate the EE around base-frame axes
                T_wb = self._get_base_transform()
                R_wb = T_wb[:3, :3]
                target_ori = R_wb @ delta_rot @ R_wb.T @ cur_ori
        else:
            target_ori = cur_ori

        self.move_ee_to_pose(target_pos, target_ori)

    def go_home(self):
        """Move the arm back to its default home configuration.

        Uses forward kinematics of the home qpos to compute the target EE
        pose, then moves there via move_ee_to_pose.
        """
        # Temporarily set joints to home to read the FK target
        saved_qpos = self.sim.data.qpos.copy()
        saved_qvel = self.sim.data.qvel.copy()

        for i, idx in enumerate(self.robot._ref_joint_pos_indexes):
            self.sim.data.qpos[idx] = self._home_qpos[i]
        self.sim.forward()

        target_pos = np.array(self.sim.data.site_xpos[self._eef_site_id]).copy()
        target_ori = self.sim.data.site_xmat[self._eef_site_id].reshape(3, 3).copy()

        # Restore state
        self.sim.data.qpos[:] = saved_qpos
        self.sim.data.qvel[:] = saved_qvel
        self.sim.forward()

        self.move_ee_to_pose(target_pos, target_ori)

    # ------------------------------------------------------------------
    # Blocking base control
    # ------------------------------------------------------------------

    def step_base_toward_pose(self, x, y, theta, num_steps=50):
        """Multiple physics steps moving the base toward a target pose.

        Non-blocking version of move_base_to_pose for streaming control.
        Runs a batch of steps per call so the SDK's 10Hz loop
        makes meaningful progress.
        """
        target_pos = np.array([x, y])
        target_yaw = theta

        for i in range(num_steps):
            cur_pos, cur_yaw = self.get_base_pose()
            pos_err = target_pos - cur_pos
            yaw_err = self._angle_diff(target_yaw, cur_yaw)
            err_mag = np.linalg.norm(pos_err)

            if err_mag < BASE_POS_TOL and abs(yaw_err) < BASE_ORI_TOL:
                break

            cos_y, sin_y = np.cos(cur_yaw), np.sin(cur_yaw)
            local_x = cos_y * pos_err[0] + sin_y * pos_err[1]
            local_y = -sin_y * pos_err[0] + cos_y * pos_err[1]

            base_action = np.clip(
                np.array([-local_x, -local_y, yaw_err]) * 20.0,
                -1.0, 1.0,
            )

            ad = self._zero_action_dict(base_mode=1)
            ad["base"] = base_action
            self._step(ad)

    def move_base_to_pose(self, x, y, theta):
        """Blocking loop: move the base to a target (x, y, theta) in world frame."""
        target_pos = np.array([x, y])
        target_yaw = theta

        for _ in range(BASE_MAX_STEPS):
            cur_pos, cur_yaw = self.get_base_pose()

            # Errors in world frame
            pos_err = target_pos - cur_pos
            yaw_err = self._angle_diff(target_yaw, cur_yaw)

            if np.linalg.norm(pos_err) < BASE_POS_TOL and abs(yaw_err) < BASE_ORI_TOL:
                break

            # Transform position error to base-local frame
            cos_y, sin_y = np.cos(cur_yaw), np.sin(cur_yaw)
            local_x = cos_y * pos_err[0] + sin_y * pos_err[1]
            local_y = -sin_y * pos_err[0] + cos_y * pos_err[1]

            # Normalise (base velocity controller, values in [-1, 1])
            # Negate xy: robosuite base controller convention is inverted
            base_action = np.clip(
                np.array([-local_x, -local_y, yaw_err]) * 20.0,
                -1.0, 1.0,
            )

            ad = self._zero_action_dict(base_mode=1)
            ad["base"] = base_action
            self._step(ad)

    @staticmethod
    def _angle_diff(a, b):
        """Compute shortest signed angle difference a - b, wrapped to [-pi, pi]."""
        d = a - b
        return (d + np.pi) % (2 * np.pi) - np.pi

    # ------------------------------------------------------------------
    # Gripper control
    # ------------------------------------------------------------------

    def gripper_open(self):
        """Step the environment with gripper-open commands."""
        self._gripper_closed = False
        for _ in range(GRIPPER_STEPS):
            ad = self._zero_action_dict(base_mode=-1)
            ad[f"{self._arm}_gripper"] = np.array([-1.0])
            self._step(ad)

    def gripper_close(self):
        """Step the environment with gripper-close commands."""
        self._gripper_closed = True
        for _ in range(GRIPPER_STEPS):
            ad = self._zero_action_dict(base_mode=-1)
            ad[f"{self._arm}_gripper"] = np.array([1.0])
            self._step(ad)

    def gripper_grasp(self):
        """Close the gripper and return True if an object is likely grasped."""
        self.gripper_close()
        state = self.get_gripper_state()
        # If fingers didn't fully close, something is between them
        return state["position"] > 0.002

    # ------------------------------------------------------------------
    # Scene management
    # ------------------------------------------------------------------

    def reset_scene(self):
        """Reset the environment to initial state."""
        self._last_obs = self.env.reset()
        self._gripper_closed = False
