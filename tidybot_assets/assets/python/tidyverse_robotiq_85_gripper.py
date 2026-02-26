"""
TidyVerse parallel-jaw gripper — simple two-finger slide gripper using
TidyVerse finger_tip meshes on the TidyVerse coupling adapter base.
Follows the Panda gripper pattern (1-DOF parallel jaw).
"""
import numpy as np

from robosuite.models.grippers.gripper_model import GripperModel
from robosuite.utils.mjcf_utils import xml_path_completion


class TidyVerseRobotiq85GripperBase(GripperModel):
    """Parallel-jaw gripper with TidyVerse coupling adapter and finger tips."""

    def __init__(self, idn=0):
        super().__init__(xml_path_completion("grippers/tidyverse_robotiq_85.xml"), idn=idn)

    def format_action(self, action):
        return action

    @property
    def init_qpos(self):
        return np.array([0.0, 0.0])

    @property
    def _important_geoms(self):
        return {
            "left_finger": ["left_finger_tip_collision"],
            "right_finger": ["right_finger_tip_collision"],
            "left_fingerpad": ["left_finger_tip_collision"],
            "right_fingerpad": ["right_finger_tip_collision"],
        }


class TidyVerseRobotiq85Gripper(TidyVerseRobotiq85GripperBase):
    """1-DOF variant that maps a single action to open/close."""

    def format_action(self, action):
        """
        Maps continuous action into binary output.
        -1 => open, 1 => closed

        Args:
            action (np.array): gripper-specific action

        Raises:
            AssertionError: [Invalid action dimension size]
        """
        assert len(action) == self.dof
        self.current_action = np.clip(
            self.current_action + np.array([1.0, -1.0]) * self.speed * np.sign(action), -1.0, 1.0
        )
        return self.current_action

    @property
    def speed(self):
        return 0.2

    @property
    def dof(self):
        return 1
