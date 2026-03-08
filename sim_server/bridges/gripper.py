"""Gripper bridge — exposes Robotiq-compatible gripper control via ZMQ.

Protocol: 2 ZMQ sockets, msgpack serialization (matches hardware gripper_server client).
  CMD   REP  port 5570  — msgpack binary commands + responses
  STATE PUB  port 5571  — msgpack state broadcast at ~10Hz
"""

import json
import threading
import time

import msgpack
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
            sock.send(msgpack.packb(msg, use_bin_type=True))
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
                raw = sock.recv()
            except zmq.Again:
                continue

            try:
                req = msgpack.unpackb(raw, raw=False)
                resp = self._dispatch_rpc(req)
            except Exception as e:
                resp = {"error": str(e)}

            sock.send(msgpack.packb(resp, use_bin_type=True))

        sock.close()
        ctx.term()

    def _dispatch_rpc(self, req):
        # Hardware gripper client sends msgpack with msg_type integers:
        # ACTIVATE=10, RESET=11, MOVE=12, OPEN=13, CLOSE=14, STOP=15, CALIBRATE=16
        # Response format: {msg_type: 100, success: bool, message: str, data: dict|None}
        msg_type = req.get("msg_type")

        def _ok(data=None):
            return {"msg_type": 100, "success": True, "message": "", "data": data}

        if msg_type == 10:  # ACTIVATE
            return _ok({"result": True})

        elif msg_type == 13:  # OPEN
            self._server.submit_command("gripper_open")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return _ok({"position": pos, "object_detected": False})

        elif msg_type == 14:  # CLOSE
            self._server.submit_command("gripper_close")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return _ok({"position": pos, "object_detected": state.gripper_object_detected})

        elif msg_type == 12:  # MOVE
            position = req.get("position", 0)
            if position < 128:
                self._server.submit_command("gripper_open")
            else:
                self._server.submit_command("gripper_close")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return _ok({"position": pos, "object_detected": state.gripper_object_detected})

        elif msg_type == 15:  # STOP
            return _ok()

        elif msg_type == 11:  # RESET
            return _ok()

        elif msg_type == 16:  # CALIBRATE
            return _ok()

        else:
            return {"msg_type": 100, "success": False, "message": f"unknown msg_type: {msg_type}", "data": None}

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
            "gripper_type": 1,  # ROBOTIQ_2F85
        }
