"""Base bridge — exposes mobile base control via multiprocessing.managers RPC.

Implements the same interface as the real base_server so the agent_server's
BaseBackend can connect transparently.

Protocol: The real base_server exposes a "Base" class via
multiprocessing.managers.BaseManager on port 50000 with authkey b"secret password".

The client (agent_server/backends/base.py) does:
    _BaseManager.register("Base")
    manager.connect()
    base = manager.Base()  # returns AutoProxy
    base.get_full_state()
    base.execute_action({"base_pose": np.array([x, y, theta])})
    base.set_target_velocity([vx, vy, wz], frame="global")
    base.stop()
    base.reset()
    base.get_battery_voltage()
    base.get_command_state()
    base.ensure_initialized()
"""

import threading
import time
from multiprocessing.managers import BaseManager

import numpy as np

BASE_RPC_PORT = 50000
BASE_RPC_AUTHKEY = b"secret password"


class SimBase:
    """Simulated base object exposed via multiprocessing.managers RPC.

    Methods match the real base_server's Base class interface exactly.
    The AutoProxy will expose all public methods to the client.

    Stores the initial base pose as the origin so the SDK sees (0,0,0) at
    startup. Translates between SDK frame and world frame in both directions
    (same pattern as the franka bridge's joint offset).
    """

    def __init__(self, sim_server):
        self._server = sim_server
        self._cmd_vel = [0.0, 0.0, 0.0]
        self._cmd_time = 0.0
        self._is_velocity_mode = False

        # Store the initial base pose as origin — SDK sees (0,0,0) at start.
        state = self._server.get_state()
        self._origin_x = state.base_x
        self._origin_y = state.base_y
        self._origin_theta = state.base_theta
        print(f"[base-bridge] Origin: x={self._origin_x:.3f}, "
              f"y={self._origin_y:.3f}, theta={self._origin_theta:.3f}")

    def _world_to_sdk(self, x, y, theta):
        """Convert world-frame pose to SDK frame (relative to origin)."""
        # Rotate position offset into origin frame
        dx = x - self._origin_x
        dy = y - self._origin_y
        cos_o = np.cos(-self._origin_theta)
        sin_o = np.sin(-self._origin_theta)
        sdk_x = cos_o * dx - sin_o * dy
        sdk_y = sin_o * dx + cos_o * dy
        sdk_theta = self._angle_wrap(theta - self._origin_theta)
        return sdk_x, sdk_y, sdk_theta

    def _sdk_to_world(self, sdk_x, sdk_y, sdk_theta):
        """Convert SDK frame pose to world frame."""
        cos_o = np.cos(self._origin_theta)
        sin_o = np.sin(self._origin_theta)
        x = self._origin_x + cos_o * sdk_x - sin_o * sdk_y
        y = self._origin_y + sin_o * sdk_x + cos_o * sdk_y
        theta = self._angle_wrap(sdk_theta + self._origin_theta)
        return x, y, theta

    @staticmethod
    def _angle_wrap(a):
        """Wrap angle to [-pi, pi]."""
        return (a + np.pi) % (2 * np.pi) - np.pi

    def ensure_initialized(self):
        """No-op in sim — base is always ready."""
        pass

    def get_full_state(self):
        """Return full base state dict matching real base_server format."""
        state = self._server.get_state()
        sdk_x, sdk_y, sdk_theta = self._world_to_sdk(
            state.base_x, state.base_y, state.base_theta
        )
        return {
            "base_pose": np.array([sdk_x, sdk_y, sdk_theta]),
            "base_velocity": np.array([state.base_vx, state.base_vy, state.base_wz]),
        }

    def execute_action(self, target):
        """Step base toward target pose (non-blocking).

        The SDK calls this at 10 Hz in its own convergence loop,
        so we only need a single physics step per call.
        Target pose is in SDK frame — convert to world frame for the sim.

        Args:
            target: dict with "base_pose" key -> np.array([x, y, theta])
        """
        pose = target["base_pose"]
        sdk_x, sdk_y, sdk_theta = float(pose[0]), float(pose[1]), float(pose[2])
        # Convert SDK frame → world frame
        world_x, world_y, world_theta = self._sdk_to_world(sdk_x, sdk_y, sdk_theta)
        self._is_velocity_mode = False
        self._cmd_vel = [0.0, 0.0, 0.0]
        self._server.submit_command("step_base_toward_pose", world_x, world_y, world_theta)

    def set_target_velocity(self, vel, frame="global"):
        """Set base velocity.

        Args:
            vel: [vx, vy, wz] list/array
            frame: "global" or "local"
        """
        self._cmd_vel = [float(vel[0]), float(vel[1]), float(vel[2])]
        self._cmd_time = time.time()
        self._is_velocity_mode = True
        # Velocity control not yet implemented in sim — log and ignore
        pass

    def stop(self):
        """Stop the base."""
        self._is_velocity_mode = False
        self._cmd_vel = [0.0, 0.0, 0.0]

    def reset(self):
        """Reset the base (no-op in sim)."""
        pass

    def get_battery_voltage(self):
        """Simulated battery voltage (always returns full charge)."""
        return 25.2

    def get_command_state(self):
        """Return command tracking state for collision detection."""
        return {
            "is_velocity_mode": self._is_velocity_mode,
            "cmd_vel": list(self._cmd_vel),
            "cmd_time": self._cmd_time,
        }


# Shared SimBase — all RPC proxies delegate to this instance.
# The factory returns a fresh wrapper each time so that each proxy gets
# a unique id(), preventing multiprocessing.managers proxy GC from
# corrupting shared thread-local connection state.
_sim_base_instance = None


class _SimBaseProxy:
    """Thin wrapper that delegates to the shared SimBase.

    Each manager.Base() call gets a new _SimBaseProxy (unique id),
    so old-proxy garbage collection can't poison new proxies.
    """

    def __init__(self, real):
        self._real = real

    def ensure_initialized(self):
        return self._real.ensure_initialized()

    def get_full_state(self):
        return self._real.get_full_state()

    def execute_action(self, target):
        return self._real.execute_action(target)

    def set_target_velocity(self, vel, frame="global"):
        return self._real.set_target_velocity(vel, frame=frame)

    def stop(self):
        return self._real.stop()

    def reset(self):
        return self._real.reset()

    def get_battery_voltage(self):
        return self._real.get_battery_voltage()

    def get_command_state(self):
        return self._real.get_command_state()


def _base_factory():
    """Return a fresh proxy wrapping the shared SimBase."""
    return _SimBaseProxy(_sim_base_instance)


class _BaseBridgeManager(BaseManager):
    pass


class BaseBridge:
    """Protocol bridge: multiprocessing.managers RPC on port 50000.

    Lifecycle managed by SimServer.add_bridge() / start_bridges() / stop_bridges().
    """

    def __init__(self, sim_server, port=BASE_RPC_PORT, authkey=BASE_RPC_AUTHKEY):
        self._sim_server = sim_server
        self._port = port
        self._authkey = authkey
        self._thread = None
        self._manager = None
        self._running = False

    def _reset_origin(self):
        """Re-calibrate the base origin after a scene reset."""
        global _sim_base_instance
        if _sim_base_instance is not None:
            state = self._sim_server.get_state()
            _sim_base_instance._origin_x = state.base_x
            _sim_base_instance._origin_y = state.base_y
            _sim_base_instance._origin_theta = state.base_theta
            print(f"[base-bridge] Origin reset: x={state.base_x:.3f}, "
                  f"y={state.base_y:.3f}, theta={state.base_theta:.3f}")

    def start(self):
        """Start the RPC server in a background thread."""
        global _sim_base_instance
        _sim_base_instance = SimBase(self._sim_server)

        self._running = True
        self._thread = threading.Thread(
            target=self._run,
            daemon=True,
            name="base-bridge",
        )
        self._thread.start()

    def stop(self):
        """Stop the RPC server."""
        self._running = False
        if self._manager is not None:
            try:
                server = self._manager.get_server()
                server.stop_event = True
            except Exception:
                pass
            self._manager = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        print("[base-bridge] Stopped")

    def _run(self):
        """Run the BaseManager server."""
        # Register "Base" — client calls manager.Base() to get the proxy
        _BaseBridgeManager.register("Base", callable=_base_factory)

        self._manager = _BaseBridgeManager(
            address=("0.0.0.0", self._port),
            authkey=self._authkey,
        )
        server = self._manager.get_server()
        print(f"[base-bridge] RPC server listening on port {self._port}")

        try:
            server.serve_forever()
        except Exception as e:
            if self._running:
                print(f"[base-bridge] Server error: {e}")
