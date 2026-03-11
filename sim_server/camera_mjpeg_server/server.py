"""Camera server — pulls frames from agent_server, caches them, serves MJPEG streams + YOLO.

This is an optional standalone server. Camera views and YOLO are also available
directly through the agent_server dashboard and API.
"""

import asyncio
import logging
import threading
import time

import httpx
from fastapi import FastAPI, HTTPException
from fastapi.responses import Response, StreamingResponse

from .config import CameraServerConfig
from .yolo_client import YOLOClient

logger = logging.getLogger("camera_server")

app = FastAPI(title="Camera Server", version="0.1.0")

# Runtime state — set by configure()
_cfg: CameraServerConfig | None = None
_yolo: YOLOClient | None = None

# Frame cache: camera_name -> (jpeg_bytes, timestamp)
_frame_cache: dict[str, tuple[bytes, float]] = {}
_cache_lock = threading.Lock()

# Capture thread handle
_capture_thread: threading.Thread | None = None
_capture_stop = threading.Event()


def configure(cfg: CameraServerConfig | None = None):
    """Set config and wire up components. Call before app starts."""
    global _cfg, _yolo
    _cfg = cfg or CameraServerConfig()
    _yolo = YOLOClient(server_url=_cfg.yolo_server_url)


def _capture_loop():
    """Background thread: poll agent_server for JPEG frames."""
    interval = 1.0 / _cfg.capture_fps
    with httpx.Client(timeout=5.0) as client:
        while not _capture_stop.is_set():
            for cam in _cfg.cameras:
                try:
                    r = client.get(f"{_cfg.agent_server_url}/api/camera/{cam}")
                    if r.status_code == 200:
                        with _cache_lock:
                            _frame_cache[cam] = (r.content, time.time())
                except Exception:
                    pass
            _capture_stop.wait(interval)


@app.on_event("startup")
async def _startup():
    global _capture_thread
    if _cfg is None:
        configure()
    _capture_stop.clear()
    _capture_thread = threading.Thread(target=_capture_loop, daemon=True)
    _capture_thread.start()
    logger.info("Capture thread started (polling %s)", _cfg.agent_server_url)


@app.on_event("shutdown")
async def _shutdown():
    _capture_stop.set()
    if _capture_thread:
        _capture_thread.join(timeout=3)
    logger.info("Capture thread stopped")


# ------------------------------------------------------------------
# Endpoints
# ------------------------------------------------------------------

@app.get("/cameras")
async def list_cameras():
    """List configured cameras and their cache status."""
    cams = []
    with _cache_lock:
        for name in _cfg.cameras:
            entry = _frame_cache.get(name)
            cams.append({
                "name": name,
                "has_frame": entry is not None,
                "last_update": entry[1] if entry else None,
            })
    return {"cameras": cams}


@app.get("/camera/{name}")
async def get_camera(name: str):
    """Return the latest cached JPEG frame."""
    with _cache_lock:
        entry = _frame_cache.get(name)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No frame for camera '{name}'")
    return Response(
        content=entry[0],
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@app.get("/camera/{name}/stream")
async def camera_stream(name: str):
    """MJPEG stream from the cached frames."""
    if name not in _cfg.cameras:
        raise HTTPException(status_code=404, detail=f"Unknown camera '{name}'")

    async def generate():
        last_ts = 0.0
        while True:
            with _cache_lock:
                entry = _frame_cache.get(name)
            if entry and entry[1] > last_ts:
                jpeg, last_ts = entry
                yield (
                    b"--frame\r\n"
                    b"Content-Type: image/jpeg\r\n"
                    b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                    b"\r\n" + jpeg + b"\r\n"
                )
            await asyncio.sleep(1.0 / _cfg.capture_fps)

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


# ------------------------------------------------------------------
# YOLO endpoints
# ------------------------------------------------------------------

@app.get("/yolo/health")
async def yolo_health():
    """Check YOLO-E server availability."""
    return await asyncio.to_thread(_yolo.health)


@app.post("/yolo/segment")
async def yolo_segment(camera: str = "robot0_agentview_center",
                       prompt: str = "object",
                       confidence: float = 0.5):
    """Capture frame and run YOLO segmentation."""
    with _cache_lock:
        entry = _frame_cache.get(camera)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No frame for camera '{camera}'")
    result = await asyncio.to_thread(_yolo.segment, entry[0], prompt, confidence)
    return result


@app.post("/yolo/segment_viz")
async def yolo_segment_viz(camera: str = "robot0_agentview_center",
                           prompt: str = "object",
                           confidence: float = 0.5):
    """Capture frame, run YOLO, return annotated JPEG."""
    with _cache_lock:
        entry = _frame_cache.get(camera)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"No frame for camera '{camera}'")
    jpeg = await asyncio.to_thread(_yolo.segment_visualization, entry[0], prompt, confidence)
    if jpeg is None:
        raise HTTPException(status_code=502, detail="YOLO server returned no visualization")
    return Response(content=jpeg, media_type="image/jpeg")
