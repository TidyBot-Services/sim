"""YOLO object detection — TidyBot-compatible API using remote segmentation server.

Uses the same remote YOLO server as the real TidyBot SDK, but sources camera
frames from the sim instead of the real robot's camera endpoint.
"""

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


def segment_image(image_bytes, confidence=0.5, classes=None):
    """Run segmentation on raw JPEG image bytes.

    Args:
        image_bytes: JPEG-encoded image bytes.
        confidence: Minimum detection confidence (0-1).
        classes: Optional list of class names to filter for.

    Returns:
        SegmentationResult with detected objects.
    """
    import httpx

    prompt = ",".join(classes) if classes else "object"
    files = {"image_file": ("frame.jpg", image_bytes, "image/jpeg")}
    data = {"text_prompt": prompt, "confidence": str(confidence)}

    resp = httpx.post(f"{YOLO_SERVER_URL}/segment", files=files, data=data, timeout=30)
    resp.raise_for_status()
    raw = resp.json()

    detections = []
    for det in raw.get("detections", raw if isinstance(raw, list) else []):
        detections.append(Detection(
            label=det.get("class_name", det.get("label", "")),
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
    jpeg_bytes = get_robot().render_camera_jpeg(camera_name)
    return segment_image(jpeg_bytes, confidence=confidence, classes=classes)


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
    import httpx

    jpeg_bytes = get_robot().render_camera_jpeg(camera_name)
    prompt = ",".join(classes) if classes else "object"
    files = {"image_file": ("frame.jpg", jpeg_bytes, "image/jpeg")}
    data = {"text_prompt": prompt, "confidence": str(confidence)}

    resp = httpx.post(f"{YOLO_SERVER_URL}/segment_visualization", files=files, data=data, timeout=30)
    resp.raise_for_status()
    return resp.content
