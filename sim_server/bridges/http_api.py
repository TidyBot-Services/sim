"""HTTP API bridge — lightweight REST API for sim control.

Exposes reset and status endpoints so the agent_server (or any client)
can trigger scene resets without going through the hardware bridges.

Runs a small Flask/http.server in a background thread.
"""

import json
import threading
import traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
from functools import partial

DEFAULT_PORT = 8081


class SimAPIHandler(BaseHTTPRequestHandler):
    """HTTP request handler for sim control endpoints."""

    def __init__(self, sim_server, *args, **kwargs):
        self._sim_server = sim_server
        super().__init__(*args, **kwargs)

    def log_message(self, format, *args):
        """Suppress default stderr logging."""
        pass

    def _send_json(self, status, data):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        if self.path == "/health":
            state = self._sim_server.get_state()
            self._send_json(200, {
                "status": "ok",
                "timestamp": state.timestamp,
                "base": [state.base_x, state.base_y, state.base_theta],
                "gripper_closed": state.gripper_closed,
            })
        elif self.path == "/status":
            self._send_json(200, {
                "running": self._sim_server._running,
                "task": self._sim_server.task,
                "robot": self._sim_server.robot_name,
                "bridges": len(self._sim_server._bridges),
            })
        else:
            self._send_json(404, {"error": "not found"})

    def do_POST(self):
        if self.path == "/reset" or self.path == "/reset/soft":
            try:
                result = self._sim_server.submit_command("reset_to_initial")
                # Re-snapshot the base bridge origin after reset
                self._reset_base_bridge_origin()
                self._send_json(200, result)
            except Exception as e:
                self._send_json(500, {
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })

        elif self.path == "/reset/hard":
            try:
                result = self._sim_server.submit_command("reset_scene")
                self._reset_base_bridge_origin()
                self._send_json(200, result)
            except Exception as e:
                self._send_json(500, {
                    "error": str(e),
                    "traceback": traceback.format_exc(),
                })
        else:
            self._send_json(404, {"error": "not found"})

    def _reset_base_bridge_origin(self):
        """Re-calibrate the base bridge origin after a scene reset."""
        for bridge in self._sim_server._bridges:
            if hasattr(bridge, '_reset_origin'):
                try:
                    bridge._reset_origin()
                except Exception as e:
                    print(f"[http-api] Warning: failed to reset bridge origin: {e}")


class HttpApiBridge:
    """HTTP API bridge for sim control.

    Lifecycle managed by SimServer.add_bridge() / start_bridges() / stop_bridges().
    """

    def __init__(self, sim_server, port=DEFAULT_PORT):
        self._sim_server = sim_server
        self._port = port
        self._thread = None
        self._httpd = None

    def start(self):
        """Start the HTTP server in a background thread."""
        handler = partial(SimAPIHandler, self._sim_server)
        self._httpd = HTTPServer(("0.0.0.0", self._port), handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            daemon=True,
            name="http-api-bridge",
        )
        self._thread.start()
        print(f"[http-api] Sim control API listening on port {self._port}")
        print(f"[http-api]   POST /reset       - soft reset (fast)")
        print(f"[http-api]   POST /reset/hard   - hard reset (full reload)")
        print(f"[http-api]   GET  /health       - sim state")

    def stop(self):
        """Stop the HTTP server."""
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd = None
        if self._thread is not None:
            self._thread.join(timeout=3)
            self._thread = None
        print("[http-api] Stopped")
