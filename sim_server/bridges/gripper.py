"""Gripper bridge — exposes Robotiq-compatible gripper control via ZMQ.

Protocol: 2 ZMQ sockets, JSON serialization (matches gripper_server client).
  CMD   REP  port 5570  — JSON RPC commands
  STATE PUB  port 5571  — JSON state broadcast at ~10Hz
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
    # State publisher (PUB socket, ~10Hz, JSON)
    # ------------------------------------------------------------------

    def _state_publisher(self):
        ctx = zmq.Context()
        sock = ctx.socket(zmq.PUB)
        sock.bind(f"tcp://*:{self._state_port}")
        print(f"[gripper-bridge] State PUB on {self._state_port}, CMD REP on {self._cmd_port}")

        interval = 1.0 / STATE_HZ
        while self._running:
            state = self._server.get_state()
            msg = self._build_state_dict(state)
            sock.send_string(json.dumps(msg))
            time.sleep(interval)

        sock.close()
        ctx.term()

    # ------------------------------------------------------------------
    # Command handler (REP socket, JSON RPC)
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
                resp = self._dispatch_rpc(req)
            except Exception as e:
                resp = {"error": str(e)}

            sock.send_string(json.dumps(resp))

        sock.close()
        ctx.term()

    def _dispatch_rpc(self, req):
        method = req.get("method", "")
        kwargs = req.get("kwargs", {})

        if method == "activate":
            return {"result": True}

        elif method == "open":
            self._server.submit_command("gripper_open")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return {"result": [pos, False]}

        elif method == "close":
            self._server.submit_command("gripper_close")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return {"result": [pos, state.gripper_object_detected]}

        elif method == "move":
            position = kwargs.get("position", 0)
            if position < 128:
                self._server.submit_command("gripper_open")
            else:
                self._server.submit_command("gripper_close")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return {"result": [pos, state.gripper_object_detected]}

        elif method == "grasp":
            self._server.submit_command("gripper_close")
            state = self._server.get_state()
            return {"result": state.gripper_object_detected}

        elif method == "stop":
            return {"result": True}

        elif method == "calibrate":
            return {"result": True}

        else:
            return {"error": f"unknown method: {method}"}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mm_to_robotiq_pos(position_mm):
        """Convert mm (0=closed, 85=open) to Robotiq (0=open, 255=closed)."""
        return int(255 * (1.0 - min(position_mm / 85.0, 1.0)))

    @staticmethod
    def _build_state_dict(state):
        position_mm = state.gripper_position_mm
        position = int(255 * (1.0 - min(position_mm / 85.0, 1.0)))
        return {
            "timestamp": time.time(),
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
