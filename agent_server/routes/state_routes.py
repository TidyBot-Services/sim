"""Robot state API endpoints."""

import asyncio
import io

import mujoco
from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse
from PIL import Image

router = APIRouter(prefix="/api", tags=["state"])

# Camera image size served by /api/camera/{name}
_CAM_WIDTH = 256
_CAM_HEIGHT = 256

# Persistent renderers — avoids creating/destroying an OpenGL context per frame.
# Keyed by (model_ptr, camera_name).
_renderers: dict[tuple, mujoco.Renderer] = {}
_scene_opt: mujoco.MjvOption | None = None


def _get_scene_opt() -> mujoco.MjvOption:
    """Lazily create shared MjvOption (hides collision geoms + sites)."""
    global _scene_opt
    if _scene_opt is None:
        _scene_opt = mujoco.MjvOption()
        _scene_opt.geomgroup[0] = False
        _scene_opt.sitegroup[:] = [False] * 6
    return _scene_opt


def _get_renderer(model) -> mujoco.Renderer:
    """Get or create a persistent renderer for the given model."""
    key = id(model)
    if key not in _renderers:
        _renderers[key] = mujoco.Renderer(model, _CAM_HEIGHT, _CAM_WIDTH)
    return _renderers[key]


def close_renderers():
    """Close all persistent renderers (call on sim stop)."""
    for r in _renderers.values():
        try:
            r.close()
        except Exception:
            pass
    _renderers.clear()


def _render_jpeg(model, data, camera: str) -> bytes:
    """Render a single JPEG frame using the persistent renderer."""
    renderer = _get_renderer(model)
    renderer.update_scene(data, camera=camera, scene_option=_get_scene_opt())
    frame = renderer.render().copy()
    buf = io.BytesIO()
    Image.fromarray(frame).save(buf, format="JPEG", quality=85)
    return buf.getvalue()


def _get_runtime():
    """Import runtime lazily to avoid circular imports."""
    from agent_server.robot_sdk import _runtime
    return _runtime


@router.get("/state")
async def get_state():
    """Return current robot state: base pose, EE pose, gripper."""
    try:
        robot = _get_runtime().get_robot()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Simulation not running")

    base_pos, base_yaw = robot.get_base_pose()
    ee_pos, _ = robot.get_ee_pose()
    gripper = robot.get_gripper_state()

    return {
        "base": {
            "x": round(float(base_pos[0]), 4),
            "y": round(float(base_pos[1]), 4),
            "theta": round(float(base_yaw), 4),
        },
        "ee": {
            "x": round(float(ee_pos[0]), 4),
            "y": round(float(ee_pos[1]), 4),
            "z": round(float(ee_pos[2]), 4),
        },
        "gripper": {
            "position": round(float(gripper["position"]), 4),
            "closed": gripper["closed"],
        },
    }


@router.get("/camera/{name}")
async def get_camera(name: str):
    """Return a single JPEG frame from the named camera."""
    try:
        robot = _get_runtime().get_robot()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Simulation not running")

    model = robot.sim.model._model
    data = robot.sim.data._data

    try:
        mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Camera '{name}' not found")

    jpeg = _render_jpeg(model, data, name)
    return Response(
        content=jpeg,
        media_type="image/jpeg",
        headers={"Cache-Control": "no-store"},
    )


@router.get("/camera/{name}/stream")
async def camera_stream(name: str):
    """MJPEG stream from the named camera.

    Returns a multipart/x-mixed-replace response that browsers can
    display directly in an <img> tag for real-time video.
    """
    try:
        robot = _get_runtime().get_robot()
    except RuntimeError:
        raise HTTPException(status_code=503, detail="Simulation not running")

    model = robot.sim.model._model
    data = robot.sim.data._data

    try:
        mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_CAMERA, name)
    except Exception:
        raise HTTPException(status_code=404, detail=f"Camera '{name}' not found")

    async def generate():
        while True:
            try:
                _get_runtime().get_robot()
            except RuntimeError:
                break
            jpeg = _render_jpeg(model, data, name)
            yield (
                b"--frame\r\n"
                b"Content-Type: image/jpeg\r\n"
                b"Content-Length: " + str(len(jpeg)).encode() + b"\r\n"
                b"\r\n" + jpeg + b"\r\n"
            )
            await asyncio.sleep(0.05)  # ~20 fps

    return StreamingResponse(
        generate(),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )
