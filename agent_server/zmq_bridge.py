"""ZMQ bridge for cross-thread SimRobot communication.

The code executor runs user Python code in a background thread.  That code
calls robot_sdk methods which ultimately need to touch MuJoCo — but MuJoCo
is not thread-safe.  This module provides:

* ``ZmqRobotProxy`` — a drop-in replacement for ``SimRobot`` that lives in
  the executor thread and forwards every method call over a ZMQ REQ/REP
  socket to the main-thread ``_zmq_server()`` in ``server.py``.

The main thread's async event loop naturally serialises the ZMQ server
coroutine with the idle-physics step loop, so no explicit locking is needed.
"""

import pickle

import zmq

ZMQ_ADDRESS = "ipc:///tmp/tidybot-sim-bridge"

# Timeout for recv() in the proxy — lets SystemExit propagate when the
# executor thread is being stopped.
_RECV_TIMEOUT_MS = 60_000


class ZmqRobotProxy:
    """Thread-side proxy that forwards method calls to the main thread."""

    def __init__(self, address: str = ZMQ_ADDRESS):
        self._address = address
        self._ctx: zmq.Context | None = None
        self._sock: zmq.Socket | None = None

    def connect(self):
        self._ctx = zmq.Context()
        self._sock = self._ctx.socket(zmq.REQ)
        self._sock.setsockopt(zmq.RCVTIMEO, _RECV_TIMEOUT_MS)
        self._sock.setsockopt(zmq.LINGER, 0)
        self._sock.connect(self._address)

    def close(self):
        if self._sock is not None:
            self._sock.close()
            self._sock = None
        if self._ctx is not None:
            self._ctx.term()
            self._ctx = None

    def __getattr__(self, name: str):
        # Avoid proxying dunder / private attrs that Python internals probe
        if name.startswith("_"):
            raise AttributeError(name)

        def _remote_call(*args, **kwargs):
            return self._send({"type": "call", "method": name,
                               "args": args, "kwargs": kwargs})
        return _remote_call

    def _send(self, msg: dict):
        if self._sock is None:
            raise RuntimeError("ZmqRobotProxy not connected")
        self._sock.send(pickle.dumps(msg))
        try:
            raw = self._sock.recv()
        except zmq.Again:
            raise TimeoutError("ZMQ recv timed out — sim may be unresponsive")
        resp = pickle.loads(raw)
        if isinstance(resp, dict) and resp.get("__error__"):
            raise RuntimeError(resp["message"])
        return resp
