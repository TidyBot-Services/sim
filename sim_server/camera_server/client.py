"""Camera server WebSocket client.

Connects to the camera bridge (or real camera_server) via WebSocket,
receives binary-framed JPEG/PNG data, and decodes into numpy arrays.
"""

from __future__ import annotations

import json
import logging
import struct
import threading
import time
from typing import Any, Callable, Dict, List, Optional

import numpy as np

try:
    from websockets.sync.client import connect as ws_connect
except ImportError:
    ws_connect = None

from sim_server.camera_server.protocol import CameraInfo, CameraStateMsg, DecodedFrame

logger = logging.getLogger(__name__)


class CameraClient:
    """Synchronous WebSocket client for the camera server."""

    def __init__(self, server_ip: str = "localhost", port: int = 5580, timeout: float = 10.0):
        self._url = f"ws://{server_ip}:{port}"
        self._timeout = timeout
        self._ws = None
        self._connected = False

        self.latest_state: Optional[CameraStateMsg] = None

        # Frame buffers: (device_id, stream_type) -> DecodedFrame
        self._frames: Dict[tuple, DecodedFrame] = {}
        self._frame_lock = threading.Lock()
        self._frame_callback: Optional[Callable[[DecodedFrame], None]] = None

        # Intrinsics cache: (stream_type, device_id) -> dict
        self._intrinsics: Dict[tuple, Dict[str, Any]] = {}

        # Recv thread
        self._recv_thread: Optional[threading.Thread] = None
        self._recv_stop = threading.Event()

    def connect(self) -> bool:
        """Connect to the camera server and fetch initial state."""
        if ws_connect is None:
            logger.error("websockets not installed")
            return False

        try:
            self._ws = ws_connect(self._url, open_timeout=self._timeout)
        except Exception as e:
            logger.error("CameraClient: connect failed: %s", e)
            return False

        # Request initial state
        try:
            self._ws.send(json.dumps({"action": "get_state"}))
            raw = self._ws.recv(timeout=self._timeout)
            msg = json.loads(raw)
            self.latest_state = CameraStateMsg.from_dict(msg)
            self._connected = True
            logger.info("CameraClient: connected, %d cameras", len(self.latest_state.cameras))
            return True
        except Exception as e:
            logger.error("CameraClient: state fetch failed: %s", e)
            self._close_ws()
            return False

    def disconnect(self):
        """Stop recv thread and close connection."""
        self._recv_stop.set()
        if self._recv_thread is not None:
            self._recv_thread.join(timeout=5)
            self._recv_thread = None
        self._close_ws()
        self._connected = False

    def _close_ws(self):
        if self._ws is not None:
            try:
                self._ws.close()
            except Exception:
                pass
            self._ws = None

    def set_frame_callback(self, callback: Callable[[DecodedFrame], None]):
        """Set a callback invoked for each received frame."""
        self._frame_callback = callback

    def get_state(self) -> Optional[CameraStateMsg]:
        """Fetch current camera state from server."""
        if not self._ws or not self._connected:
            return self.latest_state
        try:
            self._ws.send(json.dumps({"action": "get_state"}))
            raw = self._ws.recv(timeout=self._timeout)
            msg = json.loads(raw)
            self.latest_state = CameraStateMsg.from_dict(msg)
            return self.latest_state
        except Exception as e:
            logger.error("CameraClient: get_state failed: %s", e)
            return self.latest_state

    def get_intrinsics(self, stream_type: str = "color", device_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Get camera intrinsics. Tries cache first, then asks server."""
        key = (stream_type, device_id or "")
        if key in self._intrinsics:
            return self._intrinsics[key]

        if not self._ws or not self._connected:
            return None

        try:
            req = {"action": "get_intrinsics", "stream": stream_type}
            if device_id:
                req["device_id"] = device_id
            self._ws.send(json.dumps(req))
            raw = self._ws.recv(timeout=self._timeout)
            msg = json.loads(raw)
            intrinsics = msg.get("data", msg.get("intrinsics"))
            if intrinsics:
                self._intrinsics[key] = intrinsics
                return intrinsics
        except Exception as e:
            logger.debug("CameraClient: get_intrinsics failed: %s", e)

        return None

    def subscribe(
        self,
        streams: Optional[List[str]] = None,
        device_id: str = "all",
        fps: int = 15,
        quality: int = 80,
    ) -> bool:
        """Subscribe to camera streams and start recv thread."""
        if not self._ws or not self._connected:
            return False

        try:
            req = {
                "action": "subscribe",
                "streams": streams or ["color"],
                "device_id": device_id,
                "fps": fps,
                "quality": quality,
            }
            self._ws.send(json.dumps(req))
        except Exception as e:
            logger.error("CameraClient: subscribe send failed: %s", e)
            return False

        # Start recv thread
        self._recv_stop.clear()
        self._recv_thread = threading.Thread(
            target=self._recv_loop, daemon=True, name="camera-recv"
        )
        self._recv_thread.start()
        return True

    def unsubscribe(
        self,
        streams: Optional[List[str]] = None,
        device_id: str = "all",
    ) -> bool:
        """Unsubscribe from camera streams."""
        if not self._ws:
            return False
        try:
            req = {"action": "unsubscribe", "streams": streams, "device_id": device_id}
            self._ws.send(json.dumps(req))
            return True
        except Exception:
            return False

    def get_latest_frame(
        self,
        stream_type: str = "color",
        device_id: Optional[str] = None,
    ) -> Optional[DecodedFrame]:
        """Get the latest decoded frame for a given stream/device."""
        with self._frame_lock:
            if device_id:
                return self._frames.get((device_id, stream_type))
            # Return first matching stream_type
            for (did, st), frame in self._frames.items():
                if st == stream_type:
                    return frame
        return None

    # ------------------------------------------------------------------
    # Recv thread
    # ------------------------------------------------------------------

    def _recv_loop(self):
        """Receive binary frames from the WebSocket."""
        while not self._recv_stop.is_set():
            try:
                raw = self._ws.recv(timeout=1.0)
            except TimeoutError:
                continue
            except Exception:
                break

            if isinstance(raw, str):
                # JSON message (state update, etc.) — skip
                continue

            try:
                self._decode_binary_frame(raw)
            except Exception as e:
                logger.debug("CameraClient: frame decode error: %s", e)

    def _decode_binary_frame(self, data: bytes):
        """Decode binary frame: [4B header_len][JSON header][image bytes]."""
        if len(data) < 4:
            return

        header_len = struct.unpack(">I", data[:4])[0]
        if len(data) < 4 + header_len:
            return

        header = json.loads(data[4:4 + header_len])
        image_bytes = data[4 + header_len:]

        device_id = header.get("camera_id", "")
        stream_type = header.get("stream", "color")
        timestamp = header.get("timestamp", time.time())
        width = header.get("width", 0)
        height = header.get("height", 0)

        # Cache intrinsics if present in header
        intrinsics = header.get("intrinsics")
        if intrinsics and device_id:
            self._intrinsics[(stream_type, device_id)] = intrinsics

        # Decode JPEG/PNG to numpy array
        frame_array = self._decode_image(image_bytes, header.get("format", "jpeg"))
        if frame_array is None:
            return

        decoded = DecodedFrame(
            device_id=device_id,
            stream_type=stream_type,
            frame=frame_array,
            timestamp=timestamp,
            width=width,
            height=height,
        )

        with self._frame_lock:
            self._frames[(device_id, stream_type)] = decoded

        if self._frame_callback is not None:
            try:
                self._frame_callback(decoded)
            except Exception:
                pass

    @staticmethod
    def _decode_image(data: bytes, fmt: str = "jpeg") -> Optional[np.ndarray]:
        """Decode image bytes to numpy array."""
        try:
            import cv2
            arr = np.frombuffer(data, dtype=np.uint8)
            flag = cv2.IMREAD_COLOR if fmt in ("jpeg", "jpg") else cv2.IMREAD_UNCHANGED
            return cv2.imdecode(arr, flag)
        except ImportError:
            pass

        # Fallback to PIL
        try:
            from PIL import Image
            import io
            img = Image.open(io.BytesIO(data))
            return np.array(img)
        except Exception:
            return None
