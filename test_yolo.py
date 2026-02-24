"""Test YOLO: detect yellow object in the wrist camera via lease execution."""

from robot_sdk import yolo

result = yolo.segment_camera(
    camera_name="robot0_eye_in_hand",
    confidence=0.3,
    classes=["yellow object"],
)

print(f"Detections: {len(result.detections)}")
for det in result.detections:
    print(f"  {det.label}: confidence={det.confidence:.2f}, bbox={det.bbox}")
    if len(det.bbox) == 4:
        cx = (det.bbox[0] + det.bbox[2]) / 2
        cy = (det.bbox[1] + det.bbox[3]) / 2
        print(f"    center pixel: ({cx:.0f}, {cy:.0f})")
