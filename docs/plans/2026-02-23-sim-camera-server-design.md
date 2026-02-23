# Design: Sim Camera Server

**Status**: Draft — revisit later
**Date**: 2026-02-23

## Context

The real-world TidyBot uses a standalone `camera_realsense_service` (WebSocket-based, RealSense cameras, separate YOLO-E GPU server). We want an equivalent lightweight camera server for sim that can run independently and provide dashboard camera views + YOLO segmentation.

## Decisions

| Decision | Choice |
|----------|--------|
| Frame source | Pull from agent server's existing `/api/camera/{name}` endpoints |
| Protocol | Simple HTTP only (MJPEG streams + REST) |
| YOLO backend | Remote YOLO-E server only (http://158.130.109.188:8010) |
| Package location | New top-level `camera_server/` (separate from agent_server) |
| Dashboard | Agent server dashboard embeds camera server views |

## Package Structure

```
camera_server/
├── __init__.py
├── __main__.py          # python -m camera_server
├── server.py            # FastAPI app, capture loop, endpoints
├── config.py            # CameraServerConfig
├── yolo_client.py       # YOLOClient — POST frames to remote YOLO-E server
└── dashboard.py         # Standalone camera dashboard (HTML)
```

## Data Flow

```
Agent Server (8080)                Camera Server (5581)              Browser / SDK
  /api/camera/{name}  ──JPEG──>  capture thread (polls)
                                   frame_cache[cam]  ──MJPEG──>   dashboard <img>
                                                      ──JPEG───>   /camera/{name}
                                 /yolo/segment ──POST──> YOLO-E    (158.130.109.188:8010)
                                   └── capture frame + forward ──>  returns detections
```

## Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/cameras` | GET | List available cameras + status |
| `/camera/{name}` | GET | Single JPEG frame from cache |
| `/camera/{name}/stream` | GET | MJPEG stream |
| `/yolo/segment` | POST | Capture frame + run YOLO segmentation |
| `/yolo/segment_viz` | POST | Same but returns annotated JPEG |
| `/yolo/health` | GET | Check YOLO-E server availability |
| `/` | GET | Camera dashboard page |

## YOLO Integration

`YOLOClient` mirrors the real-world `camera_server/yolo_client.py`:

```
POST /yolo/segment
Body: {"camera": "robot0_agentview_center", "prompt": "banana", "confidence": 0.5}

Response: {
  "success": true,
  "detections": [
    {"class_name": "banana", "confidence": 0.92, "bbox": [x1,y1,x2,y2], "has_mask": true, "mask": "...base64..."}
  ]
}
```

Internally: grabs latest frame from cache, encodes JPEG, POSTs to YOLO-E `/segment`, returns parsed result.

## Config

```python
@dataclass
class CameraServerConfig:
    host: str = "0.0.0.0"
    port: int = 5581
    agent_server_url: str = "http://localhost:8080"
    cameras: list[str] = field(default_factory=lambda: [
        "robot0_agentview_center",
        "robot0_eye_in_hand",
    ])
    capture_fps: int = 20
    jpeg_quality: int = 85
    yolo_server_url: str = "http://158.130.109.188:8010"
```

## Agent Server Changes (when implementing)

1. **`config.py`** — Add `camera_server_url: str = ""` to `ServerConfig`
2. **`dashboard.py`** — Camera `<img>` sources switch to camera server URL when configured; fall back to local `/api/camera/` if empty
3. **`state_routes.py`** — No changes; existing endpoints stay as frame source

## Reference

- Real-world service: https://github.com/TidyBot-Services/camera_realsense_service
- YOLO-E server: http://158.130.109.188:8010 (yoloe-11l-seg.pt on CUDA)
