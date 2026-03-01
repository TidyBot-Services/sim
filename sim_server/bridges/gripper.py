"""Gripper bridge — exposes Robotiq-compatible gripper control via ZMQ.

Protocol: 2 ZMQ sockets, msgpack serialization (matches gripper_server).
  CMD  REP  port 5570  — msgpack commands
  STATE PUB port 5571  — state broadcast at ~10Hz
"""

import sys
import os
import threading
import time

import msgpack
import zmq

# Import gripper_server.protocol directly (avoid __init__.py which pulls in client/server)
import importlib.util
_proto_path = os.path.join(os.path.dirname(__file__), '..', '..', '..',
                           'hardware', 'gripper_server', 'gripper_server', 'protocol.py')
_spec = importlib.util.spec_from_file_location("_gripper_protocol", os.path.abspath(_proto_path))
_proto_mod = importlib.util.module_from_spec(_spec)
sys.modules["_gripper_protocol"] = _proto_mod  # required for dataclasses on Python 3.10
_spec.loader.exec_module(_proto_mod)
GripperStateMsg = _proto_mod.GripperStateMsg
MessageType = _proto_mod.MessageType
Response = _proto_mod.Response
unpack_command = _proto_mod.unpack_command
ActivateCmd = _proto_mod.ActivateCmd
OpenCmd = _proto_mod.OpenCmd
CloseCmd = _proto_mod.CloseCmd
MoveCmd = _proto_mod.MoveCmd
StopCmd = _proto_mod.StopCmd
CalibrateCmd = _proto_mod.CalibrateCmd

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
    # State publisher (PUB socket, ~10Hz, msgpack)
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
            sock.send(msg.pack())
            time.sleep(interval)

        sock.close()
        ctx.term()

    # ------------------------------------------------------------------
    # Command handler (REP socket, msgpack)
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
                cmd = unpack_command(raw)
                resp = self._dispatch(cmd)
            except Exception as e:
                resp = Response(success=False, message=str(e))

            sock.send(resp.pack())

        sock.close()
        ctx.term()

    def _dispatch(self, cmd):
        if isinstance(cmd, ActivateCmd):
            return Response(success=True, message="activated")

        elif isinstance(cmd, OpenCmd):
            self._server.submit_command("gripper_open")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return Response(success=True, data={"position": pos, "object_detected": False})

        elif isinstance(cmd, CloseCmd):
            self._server.submit_command("gripper_close")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return Response(success=True, data={"position": pos, "object_detected": state.gripper_object_detected})

        elif isinstance(cmd, MoveCmd):
            if cmd.position < 128:
                self._server.submit_command("gripper_open")
            else:
                self._server.submit_command("gripper_close")
            state = self._server.get_state()
            pos = self._mm_to_robotiq_pos(state.gripper_position_mm)
            return Response(success=True, data={"position": pos, "object_detected": state.gripper_object_detected})

        elif isinstance(cmd, StopCmd):
            return Response(success=True, message="stopped")

        elif isinstance(cmd, CalibrateCmd):
            return Response(success=True, message="calibrated")

        else:
            return Response(success=False, message=f"unknown command: {type(cmd).__name__}")

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
        return GripperStateMsg(
            timestamp=time.time(),
            position=position,
            position_mm=position_mm,
            is_activated=True,
            is_moving=False,
            object_detected=state.gripper_object_detected,
            is_calibrated=True,
            current=0,
            current_ma=0.0,
            fault_code=0,
            fault_message="",
        )
