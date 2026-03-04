"""Camera bridge — exposes sim cameras via WebSocket server.

Protocol: WebSocket on port 5580, matching camera_server protocol.
  Client sends JSON with MessageType ints.
  Server streams binary frames: [4B header_len BE][JSON header][JPEG bytes].
  State messages are JSON text with MessageType.STATE.
"""

import asyncio
import json
import struct
import threading
import time
from math import tan, pi

import websockets
import websockets.asyncio.server


# ---------------------------------------------------------------------------
# Inline protocol definitions (matches camera_server protocol, no external dep)
# ---------------------------------------------------------------------------

class MessageType:
    GET_STATE = 1
    STATE = 2
    SUBSCRIBE = 3
    UNSUBSCRIBE = 4
    ACK = 5
    ERROR = 6
    GET_INTRINSICS = 7
    INTRINSICS = 8


class CameraFrame:
    """Binary-framed camera data: [4B header_len BE][JSON header][image bytes]."""

    def __init__(self, device_id, stream_type, timestamp, width, height, format, data):
        self.device_id = device_id
        self.stream_type = stream_type
        self.timestamp = timestamp
        self.width = width
        self.height = height
        self.format = format
        self.data = data  # raw image bytes (JPEG/PNG)

    def pack(self) -> bytes:
        header = json.dumps({
            "type": "frame",
            "camera_id": self.device_id,
            "stream": self.stream_type,
            "width": self.width,
            "height": self.height,
            "timestamp": self.timestamp,
            "format": self.format,
        }).encode("utf-8")
        return struct.pack(">I", len(header)) + header + self.data

CAMERA_WS_PORT = 5580

# Sim cameras and their friendly names
SIM_CAMERAS = {
    "robot0_agentview_center": {"name": "base_camera", "serial": "sim_001"},
    "robot0_eye_in_hand": {"name": "wrist_camera", "serial": "sim_002"},
}

DEFAULT_WIDTH = 640
DEFAULT_HEIGHT = 480


class CameraBridge:
    """Protocol bridge: WebSocket server for camera streaming."""

    def __init__(self, sim_server, port=CAMERA_WS_PORT):
        self._server = sim_server
        self._port = port
        self._running = False
        self._thread = None
        self._loop = None
        self._intrinsics = {}  # cached per camera

    def start(self):
        self._running = True
        self._thread = threading.Thread(
            target=self._run_ws_server, daemon=True, name="camera-bridge"
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._loop is not None:
            self._loop.call_soon_threadsafe(self._loop.stop)
        if self._thread is not None:
            self._thread.join(timeout=5)
            self._thread = None
        print("[camera-bridge] Stopped")

    def _run_ws_server(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._serve())

    async def _serve(self):
        async with websockets.asyncio.server.serve(
            self._handle_client,
            "0.0.0.0",
            self._port,
        ):
            print(f"[camera-bridge] WebSocket server on port {self._port}")
            while self._running:
                await asyncio.sleep(0.5)

    async def _handle_client(self, ws):
        try:
            # Send initial state on connect (camera client expects this)
            await ws.send(self._build_state_json())

            async for raw in ws:
                try:
                    if isinstance(raw, bytes):
                        msg = json.loads(raw)
                    else:
                        msg = json.loads(raw)
                except (json.JSONDecodeError, TypeError):
                    continue

                # Support both integer "type" (protocol spec) and
                # string "action" (camera_server client convention)
                msg_type = msg.get("type")
                action = msg.get("action", "")

                if msg_type == MessageType.GET_STATE or action == "get_state":
                    await ws.send(self._build_state_json())

                elif msg_type == MessageType.GET_INTRINSICS or action == "get_intrinsics":
                    device_id = msg.get("device_id")
                    if not device_id or device_id in ("any", "all"):
                        device_id = next(iter(SIM_CAMERAS), None)
                    intrinsics = self._get_intrinsics(device_id) if device_id else {}
                    await ws.send(json.dumps({
                        "type": MessageType.INTRINSICS,
                        "data": intrinsics,
                    }))

                elif msg_type == MessageType.SUBSCRIBE or action == "subscribe":
                    fps = msg.get("fps", 15)
                    quality = msg.get("quality", 80)
                    # Send ACK before starting stream
                    await ws.send(json.dumps({
                        "type": MessageType.ACK,
                        "success": True,
                        "message": "subscribed",
                    }))
                    await self._stream_frames(ws, fps, quality)

        except websockets.ConnectionClosed:
            pass

    async def _stream_frames(self, ws, fps, quality):
        interval = 1.0 / max(fps, 1)
        cameras = list(SIM_CAMERAS.keys())

        while self._running:
            t0 = time.monotonic()

            for cam_name in cameras:
                try:
                    jpeg_bytes = await self._loop.run_in_executor(
                        None,
                        self._server.submit_command,
                        "render_camera_jpeg",
                        cam_name,
                        DEFAULT_WIDTH,
                        DEFAULT_HEIGHT,
                        quality,
                    )
                except Exception:
                    continue

                meta = SIM_CAMERAS[cam_name]
                # Use CameraFrame.pack() format for protocol compatibility
                frame = CameraFrame(
                    device_id=cam_name,
                    stream_type="color",
                    timestamp=time.time(),
                    width=DEFAULT_WIDTH,
                    height=DEFAULT_HEIGHT,
                    format="jpeg",
                    data=jpeg_bytes,
                )

                try:
                    await ws.send(frame.pack())
                except websockets.ConnectionClosed:
                    return

                # Stream depth frame for the same camera
                try:
                    depth_bytes = await self._loop.run_in_executor(
                        None,
                        self._server.submit_command,
                        "render_camera_depth",
                        cam_name,
                        DEFAULT_WIDTH,
                        DEFAULT_HEIGHT,
                    )
                except Exception:
                    depth_bytes = None

                if depth_bytes is not None:
                    depth_header = {
                        "type": "frame",
                        "camera_id": cam_name,
                        "camera_name": meta["name"],
                        "stream": "depth",
                        "width": DEFAULT_WIDTH,
                        "height": DEFAULT_HEIGHT,
                        "timestamp": time.time(),
                        "format": "png",
                        "intrinsics": self._get_intrinsics(cam_name),
                    }
                    depth_header_bytes = json.dumps(depth_header).encode("utf-8")
                    depth_msg = struct.pack(">I", len(depth_header_bytes)) + depth_header_bytes + depth_bytes

                    try:
                        await ws.send(depth_msg)
                    except websockets.ConnectionClosed:
                        return

            elapsed = time.monotonic() - t0
            sleep_time = interval - elapsed
            if sleep_time > 0:
                await asyncio.sleep(sleep_time)

    def _get_intrinsics(self, cam_name):
        if cam_name in self._intrinsics:
            return self._intrinsics[cam_name]

        # Compute synthetic intrinsics from MuJoCo camera FOV
        try:
            import mujoco
            sim_robot = self._server.sim_robot
            model = sim_robot.sim.model._model
            cam_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, cam_name)
            if cam_id < 0:
                return {}

            fovy_rad = float(model.cam_fovy[cam_id]) * pi / 180.0
            fy = DEFAULT_HEIGHT / (2.0 * tan(fovy_rad / 2.0))
            fx = fy  # square pixels
            ppx = DEFAULT_WIDTH / 2.0
            ppy = DEFAULT_HEIGHT / 2.0

            intrinsics = {
                "fx": fx, "fy": fy,
                "ppx": ppx, "ppy": ppy,
                "width": DEFAULT_WIDTH,
                "height": DEFAULT_HEIGHT,
                "depth_scale": 0.001,
            }
            self._intrinsics[cam_name] = intrinsics
            return intrinsics
        except Exception:
            return {}

    def _build_state_json(self):
        """Build state JSON string matching CameraStateMsg.pack_json() format."""
        cameras = []
        for device_id, meta in SIM_CAMERAS.items():
            cameras.append({
                "device_id": device_id,
                "name": meta["name"],
                "camera_type": "sim",
                "serial_number": meta["serial"],
                "width": DEFAULT_WIDTH,
                "height": DEFAULT_HEIGHT,
                "fps": 30,
                "streams": ["color", "depth"],
                "firmware_version": "",
            })
        return json.dumps({
            "type": MessageType.STATE,
            "data": {
                "timestamp": time.time(),
                "cameras": cameras,
                "active_streams": {},
                "is_streaming": True,
                "error": "",
            },
        })
