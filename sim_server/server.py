"""Sim server — starts MuJoCo, runs physics loop, hosts protocol bridges.

Architecture:
    MuJoCo thread (main):
        while running:
            1. Process command queue (arm move, base move, gripper, etc.)
            2. Step physics (idle stepping when no commands)
            3. Update state buffer (read by bridges)

    Bridge threads (ZMQ/RPC/WS):
        - Read from state buffer (protected by lock)
        - Enqueue commands to command queue
        - Wait for command completion via Future
"""

import os
import sys
import threading
import time
from dataclasses import dataclass, field
from queue import Queue, Empty

import numpy as np


def _setup_paths():
    """Add robocasa/ and robosuite/ to sys.path for import."""
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    for repo in ("robocasa", "robosuite"):
        repo_root = os.path.join(project_root, repo)
        if os.path.isdir(repo_root) and repo_root not in sys.path:
            sys.path.insert(0, repo_root)


# ---------------------------------------------------------------------------
# State buffer — written by MuJoCo thread, read by bridges
# ---------------------------------------------------------------------------

@dataclass
class SimState:
    """Snapshot of robot state, updated each physics step."""
    # Base
    base_x: float = 0.0
    base_y: float = 0.0
    base_theta: float = 0.0
    base_vx: float = 0.0
    base_vy: float = 0.0
    base_wz: float = 0.0

    # Arm
    joint_positions: list = field(default_factory=lambda: [0.0] * 7)
    joint_velocities: list = field(default_factory=lambda: [0.0] * 7)
    ee_pos: list = field(default_factory=lambda: [0.0, 0.0, 0.0])
    ee_ori_mat: list = field(default_factory=lambda: [1, 0, 0, 0, 1, 0, 0, 0, 1])

    # Gripper
    gripper_position: float = 0.0
    gripper_position_mm: float = 0.0
    gripper_closed: bool = False
    gripper_object_detected: bool = False

    # Timestamp
    timestamp: float = 0.0


# ---------------------------------------------------------------------------
# Command types
# ---------------------------------------------------------------------------

@dataclass
class Command:
    """A command to be processed on the MuJoCo thread."""
    method: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    future: object = None  # concurrent.futures.Future


# ---------------------------------------------------------------------------
# SimServer
# ---------------------------------------------------------------------------

class SimServer:
    """Manages the MuJoCo simulation and protocol bridges.

    All MuJoCo access happens on the main thread via the command queue.
    Bridges run in their own threads and communicate through the queue
    and state buffer.
    """

    def __init__(
        self,
        task="Kitchen",
        robot="PandaOmron",
        layout=1,
        style=1,
        has_renderer=True,
    ):
        self.task = task
        self.robot_name = robot
        self.layout = layout
        self.style = style
        self.has_renderer = has_renderer

        self._sim_robot = None
        self._running = False
        self._command_queue = Queue()
        self._state = SimState()
        self._state_lock = threading.Lock()
        self._bridges = []

    @property
    def sim_robot(self):
        return self._sim_robot

    def get_state(self) -> SimState:
        """Return a snapshot of the current state (thread-safe read)."""
        with self._state_lock:
            # Return a copy of the dataclass
            return SimState(
                base_x=self._state.base_x,
                base_y=self._state.base_y,
                base_theta=self._state.base_theta,
                base_vx=self._state.base_vx,
                base_vy=self._state.base_vy,
                base_wz=self._state.base_wz,
                joint_positions=list(self._state.joint_positions),
                joint_velocities=list(self._state.joint_velocities),
                ee_pos=list(self._state.ee_pos),
                ee_ori_mat=list(self._state.ee_ori_mat),
                gripper_position=self._state.gripper_position,
                gripper_position_mm=self._state.gripper_position_mm,
                gripper_closed=self._state.gripper_closed,
                gripper_object_detected=self._state.gripper_object_detected,
                timestamp=self._state.timestamp,
            )

    def submit_command(self, method, *args, **kwargs):
        """Submit a command to the MuJoCo thread and wait for completion.

        Returns the result of the method call.
        Raises RuntimeError if the command fails.
        """
        from concurrent.futures import Future
        future = Future()
        cmd = Command(method=method, args=args, kwargs=kwargs, future=future)
        self._command_queue.put(cmd)
        return future.result(timeout=60)  # 60s timeout for blocking commands

    def submit_command_async(self, method, *args, **kwargs):
        """Submit a command without waiting for completion. Returns a Future."""
        from concurrent.futures import Future
        future = Future()
        cmd = Command(method=method, args=args, kwargs=kwargs, future=future)
        self._command_queue.put(cmd)
        return future

    def _update_state(self):
        """Read current state from SimRobot and update the state buffer."""
        robot = self._sim_robot
        if robot is None:
            return

        base_pos, base_yaw = robot.get_base_pose()
        ee_pos, ee_ori = robot.get_ee_pose_in_base_frame()
        joints = robot.get_arm_joints()
        joint_vels = robot.get_arm_velocities()
        gripper = robot.get_gripper_state()

        with self._state_lock:
            self._state.base_x = float(base_pos[0])
            self._state.base_y = float(base_pos[1])
            self._state.base_theta = float(base_yaw)
            # Base velocity: approximate from physics state
            self._state.base_vx = 0.0
            self._state.base_vy = 0.0
            self._state.base_wz = 0.0
            self._state.joint_positions = joints.tolist()
            self._state.joint_velocities = joint_vels.tolist()
            self._state.ee_pos = ee_pos.tolist()
            self._state.ee_ori_mat = ee_ori.flatten().tolist()
            self._state.gripper_position = gripper["position"]
            # Map gripper width to 0-85mm range (Robotiq: 85mm=open, 0mm=closed)
            # Robosuite qpos: ~0 when open, ~0.08 when closed — invert.
            gripper_width = robot.get_gripper_width()
            self._state.gripper_position_mm = max(85.0 - gripper_width * 85.0 / 0.08, 0.0)
            self._state.gripper_closed = gripper["closed"]
            self._state.gripper_object_detected = False
            self._state.timestamp = time.time()

    def _process_commands(self):
        """Drain the command queue and execute commands on the MuJoCo thread.

        Returns True if any commands were processed (caller can skip idle step).
        """
        processed = False
        while True:
            try:
                cmd = self._command_queue.get_nowait()
            except Empty:
                break

            processed = True
            try:
                fn = getattr(self._sim_robot, cmd.method)
                result = fn(*cmd.args, **cmd.kwargs)
                # Update state buffer before resolving future so callers
                # read fresh state immediately after the command completes.
                self._update_state()
                if cmd.future is not None:
                    cmd.future.set_result(result)
            except Exception as e:
                if cmd.future is not None:
                    cmd.future.set_exception(e)
        return processed

    def _idle_step(self):
        """Step physics with zero action to keep the sim alive.

        Uses base_mode=1 (velocity control) with zero velocity so the
        base stays where it is. base_mode=-1 (position hold) would pull
        the base back to its last position-control target.
        """
        robot = self._sim_robot
        ad = robot._zero_action_dict(base_mode=1)
        action = robot.robot.create_action_vector(ad)
        robot._last_obs, _, _, _ = robot.env.step(action)
        if robot.env.has_renderer:
            robot.env.render()
            robot._maybe_apply_pending_cam()

    def _init_sim(self):
        """Create the SimRobot instance."""
        _setup_paths()

        from sim_server.sim_robot import SimRobot
        from sim_server.scenes import SCENE_HOOKS

        # Register custom env if needed
        hooks = SCENE_HOOKS.get(self.task)
        if hooks is not None:
            register_fn, _ = hooks
            register_fn()

        print(f"[sim] Initialising: task={self.task}, robot={self.robot_name}, "
              f"layout={self.layout}, style={self.style}")

        self._sim_robot = SimRobot(
            env_name=self.task,
            robot=self.robot_name,
            layout=self.layout,
            style=self.style,
            has_renderer=self.has_renderer,
        )

        # Post-init scene setup
        if hooks is not None:
            _, setup_fn = hooks
            setup_fn(self._sim_robot)

        print("[sim] SimRobot ready")

    def start_bridges(self):
        """Start all registered protocol bridges in background threads."""
        for bridge in self._bridges:
            bridge.start()
        if self._bridges:
            print(f"[sim] Started {len(self._bridges)} bridge(s)")

    def stop_bridges(self):
        """Stop all running bridges."""
        for bridge in self._bridges:
            bridge.stop()
        self._bridges.clear()

    def add_bridge(self, bridge):
        """Register a protocol bridge to be started with the server."""
        self._bridges.append(bridge)

    def run(self):
        """Main loop: init sim, run physics stepping + command processing.

        This runs on the main thread and blocks until stopped.
        """
        self._init_sim()
        self._running = True

        # Populate state buffer before bridges start so they can read
        # the initial robot pose (used by base bridge for origin offset).
        self._update_state()

        # Start protocol bridges
        self.start_bridges()

        # SIGUSR1 saves the current viewer camera position
        import signal
        def _save_cam(signum, frame):
            if self._sim_robot is not None:
                self._sim_robot.save_viewer_cam()
        signal.signal(signal.SIGUSR1, _save_cam)

        print("[sim] Entering physics loop (Ctrl+C to stop, kill -USR1 to save camera)")
        step_interval = 1.0 / 20  # ~20 Hz idle stepping

        try:
            while self._running:
                # 1. Process any pending commands
                had_commands = self._process_commands()

                # 2. Idle step (keeps physics/renderer alive)
                #    Skip if commands were processed — they already stepped physics.
                if not had_commands:
                    self._idle_step()

                # 3. Update state buffer for bridges
                self._update_state()

                # 4. Sleep to maintain target rate
                time.sleep(step_interval)

        except KeyboardInterrupt:
            print("\n[sim] Interrupted")
        finally:
            self._running = False
            self.stop_bridges()
            if self._sim_robot is not None:
                try:
                    self._sim_robot.env.close()
                except Exception:
                    pass
            print("[sim] Stopped")

    def stop(self):
        """Signal the main loop to stop."""
        self._running = False
