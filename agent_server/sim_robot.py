"""SimRobot — wraps a robosuite PandaOmron environment and exposes
blocking high-level control methods consumed by the robot_sdk modules."""

import numpy as np
import robocasa  # noqa: F401 — registers Kitchen env with robosuite
import robosuite
import robosuite.utils.transform_utils as T
from robosuite.utils.control_utils import orientation_error
from robosuite.controllers import load_composite_controller_config

from agent_server.config import (
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
            **env_kwargs,
        )

        # Pin the layout and style, then reset
        self.env.layout_and_style_ids = [[layout, style]]
        self._last_obs = self.env.reset()

        # Cache robot reference
        self.robot = self.env.robots[0]
        self.sim = self.env.sim

        # Fix eye-in-hand camera position for TidyVerse (longer gripper coupling)
        if robot_name == "TidyVerse":
            self._fix_eye_in_hand_camera()
        self._arm = self.robot.arms[0]  # "right"

        # Cache the initial joint configuration (used for go_home)
        self._home_qpos = self.robot.robot_model.init_qpos.copy()

        # Store the EE site id for fast lookup
        self._eef_site_id = self.robot.eef_site_id[self._arm]

        # Store base site name for reading base pose
        self._base_site_name = self.robot.robot_model.base.correct_naming("center")
        self._base_site_id = self.sim.model.site_name2id(self._base_site_name)

        # OSC output maxima — used to normalise delta commands to [-1, 1]
        self._output_max = np.array([
            ARM_OUTPUT_MAX_POS, ARM_OUTPUT_MAX_POS, ARM_OUTPUT_MAX_POS,
            ARM_OUTPUT_MAX_ORI, ARM_OUTPUT_MAX_ORI, ARM_OUTPUT_MAX_ORI,
        ])

        # Gripper state: True = closed
        self._gripper_closed = False

    def _fix_eye_in_hand_camera(self):
        """Reposition the eye_in_hand camera for the TidyVerse gripper coupling.

        Robocasa's Kitchen._postprocess_model overwrites camera positions
        from CAM_CONFIGS at model compile time. Since we don't patch robocasa,
        we fix the compiled MuJoCo model directly after env.reset().
        """
        import mujoco
        cam_name = "robot0_eye_in_hand"
        cam_id = mujoco.mj_name2id(
            self.sim.model._model, mujoco.mjtObj.mjOBJ_CAMERA, cam_name
        )
        if cam_id >= 0:
            self.sim.model._model.cam_pos[cam_id] = [-0.05, 0, 0.27]
            print(f"[sim_robot] Fixed {cam_name} camera position")

    # ------------------------------------------------------------------
    # Low-level helpers
    # ------------------------------------------------------------------

    def _step(self, action_dict):
        """Build the flat action vector and step the environment once."""
        action = self.robot.create_action_vector(action_dict)
        self._last_obs, _, _, _ = self.env.step(action)
        if self.env.has_renderer:
            self.env.render()
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

    def get_arm_joints(self):
        """Return the 7-DOF arm joint positions."""
        return np.array([
            self.sim.data.qpos[i]
            for i in self.robot._ref_joint_pos_indexes
        ])

    def get_base_pose(self):
        """Return (xy_pos[2], yaw_radians) of the base in world frame."""
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
                "Pass has_offscreen_renderer=True and use_camera_obs=True to agent_server.init()."
            )
        obs_key = f"{name}_image"
        if obs_key in self._last_obs:
            return self._last_obs[obs_key]
        raise KeyError(f"Camera '{name}' not found in observations. Available: {list(self._last_obs.keys())}")

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

    def move_ee_delta(self, dx=0.0, dy=0.0, dz=0.0, droll=0.0, dpitch=0.0, dyaw=0.0):
        """Move the EE by a delta from its current world-frame pose."""
        cur_pos, cur_ori = self.get_ee_pose()
        target_pos = cur_pos + np.array([dx, dy, dz])

        # Compose orientation delta
        delta_ori = T.euler2mat(np.array([droll, dpitch, dyaw]))
        target_ori = delta_ori @ cur_ori

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
            base_action = np.clip(
                np.array([local_x, local_y, yaw_err]) * 5.0,  # proportional gain
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
