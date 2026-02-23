"""FastAPI server for the simulated TidyBot agent server.

Run with:
    python -m agent_server.server
    mjpython -m agent_server.server
"""

import asyncio
import io
import logging
import os
import pickle
import sys
import time
from collections import deque

import zmq
import zmq.asyncio

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from agent_server.config import LeaseConfig, ServerConfig
from agent_server.zmq_bridge import ZMQ_ADDRESS

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------

app = FastAPI(title="Sim Agent Server", version="0.1.0")

# Global server config (overridden by CLI args or env vars)
_cfg = ServerConfig()


# ---------------------------------------------------------------------------
# Log capture — ring buffer that the dashboard polls
# ---------------------------------------------------------------------------

_log_buffer: deque[str] = deque(maxlen=200)
_sim_start_time: float | None = None


class _LogCapture(io.TextIOBase):
    """Tee stdout/stderr into _log_buffer while keeping original output."""

    def __init__(self, original):
        self._original = original

    def write(self, s):
        if s and s.strip():
            for line in s.rstrip("\n").split("\n"):
                _log_buffer.append(line)
        return self._original.write(s)

    def flush(self):
        return self._original.flush()

    def fileno(self):
        return self._original.fileno()

    def isatty(self):
        return self._original.isatty()


def _install_log_capture():
    """Redirect stdout & stderr through the ring buffer."""
    if not isinstance(sys.stdout, _LogCapture):
        sys.stdout = _LogCapture(sys.stdout)
    if not isinstance(sys.stderr, _LogCapture):
        sys.stderr = _LogCapture(sys.stderr)


# ---------------------------------------------------------------------------
# Runtime state
# ---------------------------------------------------------------------------

class _Runtime:
    """Holds references to the running sim, lease manager, and code executor."""

    def __init__(self):
        self.robot = None           # SimRobot instance
        self.running = False
        self.step_task = None       # asyncio.Task for background stepping
        self.zmq_task = None        # asyncio.Task for ZMQ command server
        self.lease_manager = None
        self.code_executor = None   # CodeExecutor instance
        self._stepping = False      # True while a physics step is in flight
        self._command_running = False
        self.initial_sim_state = None  # saved qpos/qvel after scene setup

    def get_robot(self):
        if self.robot is None:
            raise RuntimeError("Simulation not running")
        return self.robot

    def mark_command_start(self):
        """Mark that an SDK command is actively using the sim."""
        self._command_running = True
        if self.lease_manager:
            self.lease_manager.record_command()

    def mark_command_end(self):
        self._command_running = False


_rt = _Runtime()


# ---------------------------------------------------------------------------
# Background physics stepping
# ---------------------------------------------------------------------------

async def _step_loop():
    """Keep physics alive at ~20 Hz by stepping with zero actions.

    Skips steps while an SDK command is actively running to avoid
    conflicting with the command's own stepping.
    """
    import numpy as np

    try:
        while _rt.running and _rt.robot is not None:
            if not _rt._command_running:
                _rt._stepping = True
                try:
                    robot = _rt.robot
                    ad = robot._zero_action_dict(base_mode=-1)
                    action = robot.robot.create_action_vector(ad)
                    robot._last_obs, _, _, _ = robot.env.step(action)
                    if robot.env.has_renderer:
                        robot.env.render()
                finally:
                    _rt._stepping = False
            await asyncio.sleep(1.0 / 20)  # ~20 Hz
    except asyncio.CancelledError:
        pass
    except Exception as e:
        print(f"[server] Step loop error: {e}")


# ---------------------------------------------------------------------------
# ZMQ command server — receives SDK calls from executor thread
# ---------------------------------------------------------------------------

async def _zmq_server():
    """Receive pickled method calls from ZmqRobotProxy and dispatch them.

    Runs on the main event loop alongside _step_loop.  While a command is
    being processed the step loop is naturally suspended (single-threaded
    async), so MuJoCo is never accessed concurrently.
    """
    ctx = zmq.asyncio.Context()
    sock = ctx.socket(zmq.REP)
    sock.bind(ZMQ_ADDRESS)
    print(f"[server] ZMQ bridge listening on {ZMQ_ADDRESS}")

    try:
        while True:
            try:
                raw = await sock.recv()
            except zmq.ZMQError:
                break

            try:
                msg = pickle.loads(raw)
            except Exception as e:
                await sock.send(pickle.dumps(
                    {"__error__": True, "message": f"Bad message: {e}"}))
                continue

            if not _rt.running or _rt.robot is None:
                await sock.send(pickle.dumps(
                    {"__error__": True, "message": "Simulation not running"}))
                continue

            if msg.get("type") == "call":
                method_name = msg["method"]
                args = msg.get("args", ())
                kwargs = msg.get("kwargs", {})
                try:
                    _rt.mark_command_start()
                    fn = getattr(_rt.robot, method_name)
                    result = fn(*args, **kwargs)
                    await sock.send(pickle.dumps(result))
                except Exception as e:
                    await sock.send(pickle.dumps(
                        {"__error__": True,
                         "message": f"{type(e).__name__}: {e}"}))
                finally:
                    _rt.mark_command_end()
            else:
                await sock.send(pickle.dumps(
                    {"__error__": True, "message": f"Unknown type: {msg.get('type')}"}))
    except asyncio.CancelledError:
        pass
    finally:
        sock.close()
        ctx.term()
        print("[server] ZMQ bridge stopped")


# ---------------------------------------------------------------------------
# Lease callback
# ---------------------------------------------------------------------------

def _reset_scene():
    """Restore the simulation to the initial state saved at startup.

    Uses sim.set_state() to restore qpos/qvel directly instead of
    env.reset(), which would rebuild the entire scene XML (slow and
    looks like a restart).
    """
    if _rt.robot is None:
        return
    if _rt.initial_sim_state is not None:
        _rt.robot.sim.set_state(_rt.initial_sim_state)
        _rt.robot.sim.forward()
        _rt.robot._gripper_closed = False
    else:
        # Fallback if no saved state
        _rt.robot.reset_scene()
    print("[server] Scene reset")


def _on_lease_end():
    """Called when a lease expires or is released."""
    if _rt.robot is not None:
        _reset_scene()


# ---------------------------------------------------------------------------
# Sim control endpoints
# ---------------------------------------------------------------------------

def _register_banana_env():
    """Register the BananaTestKitchen env class (idempotent)."""
    from agent_server import setup_paths
    setup_paths()

    import robocasa  # noqa: F401 — registers Kitchen env
    from robocasa.environments.kitchen.kitchen import Kitchen

    # Only define once
    if "BananaTestKitchen" not in globals():
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

        globals()["BananaTestKitchen"] = BananaTestKitchen


def _setup_banana_scene(robot):
    """Place robot at kitchen center and banana under the gripper."""
    import numpy as np
    import robosuite.utils.transform_utils as T
    from robocasa.utils.env_utils import set_robot_to_position

    # Find kitchen center from floor geom
    floor_body_id = robot.sim.model.body_name2id("floor_room_main")
    kitchen_center = robot.sim.model.body_pos[floor_body_id].copy()
    print(f"[server] Kitchen center (from floor): {kitchen_center}")

    # Robot -> kitchen center, facing +X
    set_robot_to_position(robot.env, kitchen_center)

    # Correct yaw so robot faces forward
    anchor_yaw = T.mat2euler(T.euler2mat(robot.env.init_robot_base_ori_anchor))[2]
    yaw_joint_name = "mobilebase0_joint_mobile_yaw"
    robot.sim.data.qpos[robot.sim.model.get_joint_qpos_addr(yaw_joint_name)] = -anchor_yaw

    # Place banana directly under the gripper on the floor
    robot.sim.forward()
    grip_site_id = robot.env.robots[0].eef_site_id["right"]
    grip_pos = robot.sim.data.site_xpos[grip_site_id].copy()

    banana = robot.env.objects["banana"]
    banana_pos = np.array([grip_pos[0], grip_pos[1], 0.01])
    banana_quat = np.array([1.0, 0.0, 0.0, 0.0])
    robot.sim.data.set_joint_qpos(
        banana.joints[0],
        np.concatenate([banana_pos, banana_quat]),
    )
    robot.sim.forward()
    print("[server] Banana placed under gripper")


class StartRequest(BaseModel):
    gui: bool = True


@app.post("/api/start")
async def start_sim(body: StartRequest = StartRequest()):
    """Create the SimRobot and start the background stepping loop."""
    global _sim_start_time
    if _rt.running:
        return {"ok": True, "message": "already running"}

    # Import and init (heavy — loads MuJoCo)
    from agent_server import init

    mode = "GUI" if body.gui else "Server"
    print(f"[server] Starting sim ({mode}): task={_cfg.task}, robot={_cfg.robot}, "
          f"layout={_cfg.layout}, style={_cfg.style}")

    # Register custom env if needed
    if _cfg.task == "BananaTestKitchen":
        _register_banana_env()

    robot = init(
        task=_cfg.task,
        robot=_cfg.robot,
        layout=_cfg.layout,
        style=_cfg.style,
        has_renderer=body.gui,
        robot_spawn_deviation_pos_x=0.0,
        robot_spawn_deviation_pos_y=0.0,
        robot_spawn_deviation_rot=0.0,
    )

    # Post-init scene setup
    if _cfg.task == "BananaTestKitchen":
        _setup_banana_scene(robot)

    # Snapshot the initial physics state so we can restore it cheaply
    # instead of calling env.reset() which rebuilds the entire scene XML.
    _rt.initial_sim_state = robot.sim.get_state()

    _rt.robot = robot
    _rt.running = True
    _sim_start_time = time.time()
    _rt.step_task = asyncio.create_task(_step_loop())

    print("[server] Simulation ready")
    return {"ok": True, "message": "simulation started"}


@app.post("/api/stop")
async def stop_sim():
    """Stop the simulation and clean up."""
    global _sim_start_time
    if not _rt.running:
        return {"ok": True, "message": "already stopped"}

    _rt.running = False
    _sim_start_time = None
    if _rt.step_task:
        _rt.step_task.cancel()
        try:
            await _rt.step_task
        except asyncio.CancelledError:
            pass
        _rt.step_task = None

    # Close persistent camera renderers before closing the env
    from agent_server.routes.state_routes import close_renderers
    close_renderers()

    if _rt.robot is not None:
        try:
            _rt.robot.env.close()
        except Exception:
            pass
        _rt.robot = None

    # Clear the runtime singleton
    from agent_server.robot_sdk import _runtime
    _runtime._sim_robot = None

    return {"ok": True, "message": "simulation stopped"}


@app.post("/api/reset")
async def reset_scene():
    """Reset the environment to initial state."""
    if not _rt.running or _rt.robot is None:
        raise HTTPException(status_code=409, detail="Simulation not running")
    _reset_scene()
    return {"ok": True, "message": "scene reset"}


@app.get("/api/sim_status")
async def sim_status():
    uptime = None
    if _rt.running and _sim_start_time:
        uptime = int(time.time() - _sim_start_time)
    return {"running": _rt.running, "uptime": uptime, "has_cameras": _rt.running}


@app.get("/api/logs")
async def get_logs():
    return {"logs": list(_log_buffer)}


# ---------------------------------------------------------------------------
# Include route modules
# ---------------------------------------------------------------------------

from agent_server.routes.dashboard import router as dashboard_router
from agent_server.routes.lease_routes import router as lease_router, set_lease_manager
from agent_server.routes.code_routes import (
    router as code_router,
    set_code_executor,
    set_lease_manager as set_code_lease_manager,
)
from agent_server.routes.state_routes import router as state_router

app.include_router(dashboard_router)
app.include_router(lease_router)
app.include_router(code_router)
app.include_router(state_router)


# ---------------------------------------------------------------------------
# Startup / shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
async def on_startup():
    _install_log_capture()

    from agent_server.code_executor import CodeExecutor
    from agent_server.lease import LeaseManager

    # Create code executor
    _rt.code_executor = CodeExecutor()
    set_code_executor(_rt.code_executor)

    # Create lease manager — stop code executor before scene reset on lease end
    _rt.lease_manager = LeaseManager(
        _cfg.lease,
        on_lease_end=_on_lease_end,
        on_code_stop=lambda reason: _rt.code_executor.stop(reason),
    )
    set_lease_manager(_rt.lease_manager)
    set_code_lease_manager(_rt.lease_manager)
    await _rt.lease_manager.start()

    # Start ZMQ bridge for executor-thread → main-thread communication
    _rt.zmq_task = asyncio.create_task(_zmq_server())

    print(f"[server] Dashboard at http://{_cfg.host}:{_cfg.port}/")


@app.on_event("shutdown")
async def on_shutdown():
    if _rt.lease_manager:
        await _rt.lease_manager.stop()
    # Stop ZMQ bridge
    if _rt.zmq_task:
        _rt.zmq_task.cancel()
        try:
            await _rt.zmq_task
        except asyncio.CancelledError:
            pass
        _rt.zmq_task = None
    # Stop sim if still running
    if _rt.running:
        await stop_sim()


# ---------------------------------------------------------------------------
# __main__
# ---------------------------------------------------------------------------

def main():
    """Entry point for ``python -m agent_server.server``."""
    import argparse
    import uvicorn

    parser = argparse.ArgumentParser(description="Sim Agent Server")
    parser.add_argument("--host", default=_cfg.host)
    parser.add_argument("--port", type=int, default=_cfg.port)
    parser.add_argument("--task", default=_cfg.task)
    parser.add_argument("--robot", default=_cfg.robot)
    parser.add_argument("--layout", type=int, default=_cfg.layout)
    parser.add_argument("--style", type=int, default=_cfg.style)
    args = parser.parse_args()

    _cfg.host = args.host
    _cfg.port = args.port
    _cfg.task = args.task
    _cfg.robot = args.robot
    _cfg.layout = args.layout
    _cfg.style = args.style

    uvicorn.run(app, host=_cfg.host, port=_cfg.port, log_level="info")


if __name__ == "__main__":
    main()
