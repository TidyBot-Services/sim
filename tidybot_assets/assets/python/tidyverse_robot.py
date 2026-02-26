"""TidyVerse compositional robot model — Panda arm on TidyVerse mobile base."""
import numpy as np

from robosuite.models.robots.compositional import Panda


class TidyVerse(Panda):
    def __init__(self, idn=0):
        super().__init__(idn=idn)
        # The base mesh already includes link0 geometry, so remove the
        # Panda arm's link0 visual geoms to avoid double-rendering.
        target = f"{self.naming_prefix}link0"
        prefix_len = len(self.naming_prefix)
        for body in self.worldbody.iter("body"):
            if body.get("name") == target:
                for geom in list(body.findall("geom")):
                    if geom.get("group") == "1":
                        prefixed_name = geom.get("name")
                        if prefixed_name is not None:
                            unprefixed = prefixed_name[prefix_len:]
                            if unprefixed in self._visual_geoms:
                                self._visual_geoms.remove(unprefixed)
                        body.remove(geom)
                break

    @property
    def default_base(self):
        return "TidyVerseBase"

    @property
    def default_arms(self):
        return {"right": "Panda"}

    @property
    def default_gripper(self):
        return {"right": "TidyVerseRobotiq85Gripper"}

    @property
    def gripper_mount_pos_offset(self):
        return {"right": [0.0, 0.0, 0.1935]}

    @property
    def init_qpos(self):
        return np.array([0, -0.785, 0, -2.0, 0, 1.571, 0.785])

    @property
    def init_torso_qpos(self):
        return np.array([])

    @property
    def base_xpos_offset(self):
        return {
            "bins": (-0.6, -0.1, 0),
            "empty": (-0.6, 0, 0),
            "table": lambda table_length: (-0.16 - table_length / 2, 0, 0),
        }
