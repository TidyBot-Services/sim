"""Scene registration and post-init setup for custom sim environments."""

import numpy as np


_registered = set()


def register_banana_env():
    """Register the BananaTestKitchen env class (idempotent)."""
    if "BananaTestKitchen" in _registered:
        return

    import robocasa  # noqa: F401 — registers Kitchen env
    from robocasa.environments.kitchen.kitchen import Kitchen

    class BananaTestKitchen(Kitchen):
        def _get_obj_cfgs(self):
            return [
                dict(
                    name="banana",
                    obj_groups="banana",
                    graspable=True,
                    placement=dict(
                        size=(0.30, 0.30),
                        pos=(0, 0),
                    ),
                ),
            ]

    # Register with robosuite's env registry
    import robosuite
    robosuite.environments.base.REGISTERED_ENVS["BananaTestKitchen"] = BananaTestKitchen
    _registered.add("BananaTestKitchen")


def setup_banana_scene(sim_robot):
    """Place robot at kitchen center and banana under the gripper."""
    import robosuite.utils.transform_utils as T
    from robocasa.utils.env_utils import set_robot_to_position

    # Find kitchen center from floor geom
    floor_body_id = sim_robot.sim.model.body_name2id("floor_room_main")
    kitchen_center = sim_robot.sim.model.body_pos[floor_body_id].copy()
    print(f"[sim] Kitchen center (from floor): {kitchen_center}")

    # Robot -> kitchen center, facing +X
    set_robot_to_position(sim_robot.env, kitchen_center)

    # Correct yaw so robot faces forward
    anchor_yaw = T.mat2euler(T.euler2mat(sim_robot.env.init_robot_base_ori_anchor))[2]
    yaw_joint_name = "mobilebase0_joint_mobile_yaw"
    sim_robot.sim.data.qpos[sim_robot.sim.model.get_joint_qpos_addr(yaw_joint_name)] = -anchor_yaw

    # Place banana directly under the gripper on the floor
    sim_robot.sim.forward()
    grip_site_id = sim_robot.env.robots[0].eef_site_id["right"]
    grip_pos = sim_robot.sim.data.site_xpos[grip_site_id].copy()

    banana = sim_robot.env.objects["banana"]
    banana_pos = np.array([grip_pos[0], grip_pos[1], 0.01])
    banana_quat = np.array([1.0, 0.0, 0.0, 0.0])
    sim_robot.sim.data.set_joint_qpos(
        banana.joints[0],
        np.concatenate([banana_pos, banana_quat]),
    )
    sim_robot.sim.forward()
    print("[sim] Banana placed under gripper")


# Map of task names to (register_fn, setup_fn) pairs
SCENE_HOOKS = {
    "BananaTestKitchen": (register_banana_env, setup_banana_scene),
}
