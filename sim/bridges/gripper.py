"""Gripper bridge — exposes Robotiq-compatible gripper control via ZMQ.

Protocol: 2 ZMQ sockets, JSON serialization.
  CMD  REP  port 5570  — JSON RPC commands
  STATE PUB port 5571  — state broadcast at ~10Hz
"""

import json
import threading
import time

import zmq

GRIPPER_CMD_PORT = 5570
GRIPPER_STATE_PORT = 5571
STATE_HZ = 10


class GripperBridge:
    """Protocol bridge: ZMQ REP + PUB for Robotiq-style gripper control."""

    def __init__(self, sim_server, cmd_port=GRIPPER_CMD_PORT, state_port=GRIPPER_STATE_PORT):
        self._server = sim_server
        self._cmd_port = cmd_port
        self._state_port = state_port
        self._running = False
        self._threads = []

    def start(self):
        self._running = True
        for target, name in [
            (self._state_publisher, "gripper-state-pub"),
            (self._command_handler, "gripper-cmd-handler"),
        ]:
            t = threading.Thread(target=target, daemon=True, name=name)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._running = False
        for t in self._threads:
            t.join(timeout=3)
        self._threads.clear()
        print("[gripper-bridge] Stopped")

    # ------------------------------------------------------------------
    # State publisher (PUB socket, ~10Hz)
    # ------------------------------------------------------------------

    def _state_publisher(self):
        ctx = zmq.Context()
        sock = ctx.socket(zmq.PUB)
        sock.bind(f"tcp://*:{self._state_port}")
        print(f"[gripper-bridge] State PUB on {self._state_port}, CMD REP on {self._cmd_port}")

        interval = 1.0 / STATE_HZ
        while self._running:
            state = self._server.get_state()
            msg = self._build_state_msg(state)
            sock.send_string(json.dumps(msg))
            time.sleep(interval)

        sock.close()
        ctx.term()

    # ------------------------------------------------------------------
    # Command handler (REP socket)
    # ------------------------------------------------------------------

    def _command_handler(self):
        ctx = zmq.Context()
        sock = ctx.socket(zmq.REP)
        sock.bind(f"tcp://*:{self._cmd_port}")
        sock.setsockopt(zmq.RCVTIMEO, 500)

        while self._running:
            try:
                raw = sock.recv_string()
            except zmq.Again:
                continue

            try:
                req = json.loads(raw)
                result, error = self._dispatch(req)
                resp = {"result": result, "error": error}
            except Exception as e:
                resp = {"result": None, "error": str(e)}

            sock.send_string(json.dumps(resp))

        sock.close()
        ctx.term()

    def _dispatch(self, req):
        method = req.get("method", "")
        args = req.get("args", [])
        kwargs = req.get("kwargs", {})

        if method == "activate":
            return True, None
        elif method == "open":
            self._server.submit_command("gripper_open")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return [pos, False], None
        elif method == "close":
            self._server.submit_command("gripper_close")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return [pos, state.gripper_object_detected], None
        elif method == "grasp":
            result = self._server.submit_command("gripper_grasp")
            return result, None
        elif method == "move":
            position = kwargs.get("position", args[0] if args else 128)
            if position < 128:
                self._server.submit_command("gripper_open")
            else:
                self._server.submit_command("gripper_close")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return [pos, state.gripper_object_detected], None
        elif method == "stop":
            return True, None
        elif method == "calibrate":
            return True, None
        else:
            return None, f"unknown method: {method}"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mm_to_robotiq_pos(position_mm):
        """Convert mm (0=closed, 85=open) to Robotiq (0=open, 255=closed)."""
        return int(255 * (1.0 - min(position_mm / 85.0, 1.0)))

    @staticmethod
    def _build_state_msg(state):
        position_mm = state.gripper_position_mm
        position = int(255 * (1.0 - min(position_mm / 85.0, 1.0)))
        return {
            "position": position,
            "position_mm": position_mm,
            "is_activated": True,
            "is_moving": False,
            "object_detected": state.gripper_object_detected,
            "is_calibrated": True,
            "current": 0,
            "current_ma": 0.0,
            "fault_code": 0,
            "fault_message": "",
        }
