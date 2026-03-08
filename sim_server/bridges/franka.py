"""Franka arm bridge — exposes Franka-compatible arm control via ZMQ.

Protocol: 3 ZMQ sockets, msgpack serialization.
  CMD    REP  port 5555  — blocking commands (get_state, set_control_mode, etc.)
  STATE  PUB  port 5556  — state broadcast at ~100Hz
  STREAM SUB  port 5557  — streaming commands (joint pos, cartesian pose)
"""

import threading
import time

import msgpack
import numpy as np
import zmq

FRANKA_CMD_PORT = 5555
FRANKA_STATE_PORT = 5556
FRANKA_STREAM_PORT = 5557

STATE_HZ = 100
STREAM_HZ = 50  # match SDK command rate for better convergence

# Message types
MSG_JOINT_POSITION_CMD = 10
MSG_JOINT_VELOCITY_CMD = 11
MSG_CARTESIAN_POSE_CMD = 13
MSG_CARTESIAN_VELOCITY_CMD = 14
MSG_SET_CONTROL_MODE = 20
MSG_SET_GAINS = 21
MSG_STOP = 22
MSG_GET_STATE = 24


class FrankaBridge:
    """Protocol bridge: ZMQ REP + PUB + SUB for Franka arm control."""

    def __init__(self, sim_server,
                 cmd_port=FRANKA_CMD_PORT,
                 state_port=FRANKA_STATE_PORT,
                 stream_port=FRANKA_STREAM_PORT):
        self._server = sim_server
        self._cmd_port = cmd_port
        self._state_port = state_port
        self._stream_port = stream_port
        self._running = False
        self._threads = []

        self._control_mode = 0
        self._stream_target = None  # (pos, ori_mat) or None
        self._stream_lock = threading.Lock()

    def start(self):
        # Cache joint offset: add to sim joints → SDK joints
        sim_robot = self._server.sim_robot
        self._joint_offset = sim_robot._joint_offset if sim_robot else np.zeros(7)

        self._running = True
        for target, name in [
            (self._state_publisher, "franka-state-pub"),
            (self._command_handler, "franka-cmd-handler"),
            (self._stream_receiver, "franka-stream-recv"),
        ]:
            t = threading.Thread(target=target, daemon=True, name=name)
            t.start()
            self._threads.append(t)

    def stop(self):
        self._running = False
        for t in self._threads:
            t.join(timeout=3)
        self._threads.clear()
        print("[franka-bridge] Stopped")

    # ------------------------------------------------------------------
    # State publisher (PUB socket, ~100Hz)
    # ------------------------------------------------------------------

    def _state_publisher(self):
        ctx = zmq.Context()
        sock = ctx.socket(zmq.PUB)
        sock.bind(f"tcp://*:{self._state_port}")
        print(f"[franka-bridge] State PUB on {self._state_port}, "
              f"CMD REP on {self._cmd_port}, "
              f"Stream SUB on {self._stream_port}")

        interval = 1.0 / STATE_HZ
        while self._running:
            state = self._server.get_state()
            msg = self._build_state_msg(state)
            sock.send(msgpack.packb(msg, use_bin_type=True))
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
                raw = sock.recv()
            except zmq.Again:
                continue

            try:
                req = msgpack.unpackb(raw, raw=False)
                resp = self._dispatch_cmd(req)
            except Exception as e:
                resp = {"error": str(e)}

            sock.send(msgpack.packb(resp, use_bin_type=True))

        sock.close()
        ctx.term()

    def _dispatch_cmd(self, req):
        msg_type = req.get("msg_type", -1)

        if msg_type == MSG_GET_STATE:
            state = self._server.get_state()
            return self._build_state_msg(state)
        elif msg_type == MSG_SET_CONTROL_MODE:
            self._control_mode = req.get("control_mode", 0)
            return {"msg_type": msg_type, "success": True}
        elif msg_type == MSG_SET_GAINS:
            return {"msg_type": msg_type, "success": True}
        elif msg_type == MSG_STOP:
            with self._stream_lock:
                self._stream_target = None
            return {"msg_type": msg_type, "success": True}
        else:
            return {"msg_type": msg_type, "success": True}

    # ------------------------------------------------------------------
    # Stream receiver (SUB socket → command queue at physics rate)
    # ------------------------------------------------------------------

    def _stream_receiver(self):
        ctx = zmq.Context()
        sock = ctx.socket(zmq.SUB)
        sock.setsockopt(zmq.SUBSCRIBE, b"")
        sock.setsockopt(zmq.CONFLATE, 1)
        sock.bind(f"tcp://*:{self._stream_port}")
        sock.setsockopt(zmq.RCVTIMEO, 100)

        interval = 1.0 / STREAM_HZ
        while self._running:
            # Drain latest message from SUB socket
            got_msg = False
            try:
                raw = sock.recv()
                got_msg = True
            except zmq.Again:
                pass

            if got_msg:
                try:
                    msg = msgpack.unpackb(raw, raw=False)
                    self._handle_stream_msg(msg)
                except Exception:
                    pass

            # Submit latest target to command queue at physics rate
            with self._stream_lock:
                target = self._stream_target

            if target is not None:
                pos, ori_mat = target
                try:
                    self._server.submit_command(
                        "track_ee_pose_step",
                        np.array(pos),
                        np.array(ori_mat),
                    )
                except Exception:
                    pass

            time.sleep(interval)

        sock.close()
        ctx.term()

    def _handle_stream_msg(self, msg):
        msg_type = msg.get("msg_type", -1)

        if msg_type == MSG_JOINT_POSITION_CMD:
            q = msg.get("q", [])
            if len(q) == 7:
                try:
                    # Remap SDK joints → sim joints (inverse of state offset)
                    q_sim = [q[i] - self._joint_offset[i] for i in range(7)]
                    pos, ori_mat = self._server.submit_command(
                        "joint_positions_to_ee_pose", q_sim
                    )
                    with self._stream_lock:
                        self._stream_target = (pos.tolist(), ori_mat.tolist())
                except Exception:
                    pass

        elif msg_type == MSG_CARTESIAN_POSE_CMD:
            pose = msg.get("pose", [])
            if len(pose) == 16:
                pos, ori_mat = self._column_major_4x4_to_pos_ori(pose)
                with self._stream_lock:
                    self._stream_target = (pos, ori_mat)

        # MSG_CARTESIAN_VELOCITY_CMD and MSG_JOINT_VELOCITY_CMD: ignored

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_state_msg(self, state):
        o_t_ee = self._pos_ori_to_column_major_4x4(state.ee_pos, state.ee_ori_mat)
        now = time.time()
        # Remap joints: sim space → SDK space (so init_qpos reports as SDK HOME)
        q_sdk = [state.joint_positions[i] + self._joint_offset[i] for i in range(7)]
        # Report zero joint velocities to the SDK. The sim OSC controller
        # always has small residual oscillations that never fully settle,
        # which blocks the SDK's convergence check (max_vel < 0.05).
        # Position/orientation error is the meaningful convergence criterion.
        dq = [0.0] * 7
        return {
            "q": q_sdk,
            "dq": dq,
            "O_T_EE": o_t_ee,
            "O_T_EE_d": o_t_ee,
            "O_F_ext_hat_K": [0.0] * 6,
            "K_F_ext_hat_K": [0.0] * 6,
            "tau_J": [0.0] * 7,
            "tau_ext_hat_filtered": [0.0] * 7,
            "q_d": q_sdk,
            "dq_d": [0.0] * 7,
            "robot_mode": 1,
            "control_mode": self._control_mode,
            "timestamp": now,
            "robot_time": now,
            "elbow": [0.0, 1.0],
        }

    @staticmethod
    def _pos_ori_to_column_major_4x4(ee_pos, ee_ori_mat):
        """Convert pos[3] + row-major 3x3 → column-major 4x4 flat list.

        ee_ori_mat is row-major: [r00, r01, r02, r10, r11, r12, r20, r21, r22]
        O_T_EE is column-major 4x4:
          [r00, r10, r20, 0, r01, r11, r21, 0, r02, r12, r22, 0, x, y, z, 1]
        """
        r = ee_ori_mat
        x, y, z = ee_pos
        return [
            r[0], r[3], r[6], 0.0,
            r[1], r[4], r[7], 0.0,
            r[2], r[5], r[8], 0.0,
            x, y, z, 1.0,
        ]

    @staticmethod
    def _column_major_4x4_to_pos_ori(pose):
        """Convert column-major 4x4 flat list → (pos[3], row-major 3x3 flat list).

        Inverse of _pos_ori_to_column_major_4x4.
        """
        pos = [pose[12], pose[13], pose[14]]
        ori_mat = [
            pose[0], pose[4], pose[8],
            pose[1], pose[5], pose[9],
            pose[2], pose[6], pose[10],
        ]
        return pos, ori_mat
