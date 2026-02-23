"""YOLO object detection — TidyBot-compatible API using remote segmentation server.

Uses the same remote YOLO server as the real TidyBot SDK, but sources camera
frames from the sim instead of the real robot's camera endpoint.
"""

import io
import warnings
from dataclasses import dataclass, field

from ._runtime import get_robot

YOLO_SERVER_URL = "http://158.130.109.188:8010"


@dataclass
class Detection:
    """A single detected object."""
    label: str
    confidence: float
    bbox: list  # [x1, y1, x2, y2]
    mask: list = field(default_factory=list)  # [[x, y], ...] polygon points


@dataclass
class SegmentationResult:
    """Result from a 2D segmentation request."""
    detections: list  # list of Detection
    image_width: int = 0
    image_height: int = 0


@dataclass
class Detection3D:
    """A detected object with 3D position estimate."""
    label: str
    confidence: float
    bbox: list
    mask: list = field(default_factory=list)
    position_3d: list = field(default_factory=list)  # [x, y, z] in world frame


@dataclass
class SegmentationResult3D:
    """Result from a 3D segmentation request."""
    detections: list  # list of Detection3D
    image_width: int = 0
    image_height: int = 0


def _encode_frame_to_jpeg(frame):
    """Encode a numpy RGB array (H, W, 3) to JPEG bytes."""
    from PIL import Image
    img = Image.fromarray(frame)
    buf = io.BytesIO()
    img.save(buf, format="JPEG")
    return buf.getvalue()


def segment_image(image_bytes, confidence=0.5, classes=None):
    """Run segmentation on raw JPEG image bytes.

    Args:
        image_bytes: JPEG-encoded image bytes.
        confidence: Minimum detection confidence (0-1).
        classes: Optional list of class names to filter for.

    Returns:
        SegmentationResult with detected objects.
    """
    import requests

    files = {"file": ("frame.jpg", image_bytes, "image/jpeg")}
    data = {"confidence": str(confidence)}
    if classes:
        data["classes"] = ",".join(classes)

    resp = requests.post(f"{YOLO_SERVER_URL}/segment", files=files, data=data, timeout=30)
    resp.raise_for_status()
    raw = resp.json()

    detections = []
    for det in raw:
        detections.append(Detection(
            label=det.get("label", ""),
            confidence=det.get("confidence", 0.0),
            bbox=det.get("bbox", []),
            mask=det.get("mask", []),
        ))

    return SegmentationResult(detections=detections)


def segment_camera(camera_name="robot0_agentview_center", confidence=0.5, classes=None):
    """Capture a frame from the sim camera and run segmentation.

    Args:
        camera_name: Name of the sim camera to use.
        confidence: Minimum detection confidence (0-1).
        classes: Optional list of class names to filter for.

    Returns:
        SegmentationResult with detected objects.
    """
    frame = get_robot().get_camera_frame(camera_name)
    jpeg_bytes = _encode_frame_to_jpeg(frame)
    result = segment_image(jpeg_bytes, confidence=confidence, classes=classes)

    # Record image dimensions from the frame
    result.image_height, result.image_width = frame.shape[:2]
    return result


def segment_camera_3d(camera_name="robot0_agentview_center", confidence=0.5, classes=None):
    """Capture a frame and run 3D segmentation (requires depth + intrinsics).

    Not yet supported in sim — depth buffer not available by default.
    Falls back to 2D segmentation with a warning.
    """
    warnings.warn(
        "segment_camera_3d() not fully supported in sim — depth not available. "
        "Returning 2D detections without 3D positions.",
        stacklevel=2,
    )
    result_2d = segment_camera(camera_name, confidence=confidence, classes=classes)

    detections_3d = []
    for det in result_2d.detections:
        detections_3d.append(Detection3D(
            label=det.label,
            confidence=det.confidence,
            bbox=det.bbox,
            mask=det.mask,
            position_3d=[],
        ))

    return SegmentationResult3D(
        detections=detections_3d,
        image_width=result_2d.image_width,
        image_height=result_2d.image_height,
    )


def segment_visualization(camera_name="robot0_agentview_center", confidence=0.5, classes=None):
    """Return an annotated JPEG image with detection overlays.

    Args:
        camera_name: Name of the sim camera to use.
        confidence: Minimum detection confidence (0-1).
        classes: Optional list of class names to filter for.

    Returns:
        JPEG bytes of the annotated image.
    """
    frame = get_robot().get_camera_frame(camera_name)
    jpeg_bytes = _encode_frame_to_jpeg(frame)

    import requests

    files = {"file": ("frame.jpg", jpeg_bytes, "image/jpeg")}
    data = {"confidence": str(confidence)}
    if classes:
        data["classes"] = ",".join(classes)

    resp = requests.post(f"{YOLO_SERVER_URL}/segment_visualization", files=files, data=data, timeout=30)
    resp.raise_for_status()
    return resp.content
