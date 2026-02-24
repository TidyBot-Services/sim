"""YOLO-E client — POST frames to a remote YOLO-E segmentation server."""

import io
import logging

import httpx

logger = logging.getLogger("agent_server.yolo")


class YOLOClient:
    """Synchronous client for the remote YOLO-E server."""

    def __init__(self, server_url: str = "http://158.130.109.188:8010",
                 timeout: float = 30.0, default_confidence: float = 0.5):
        self.server_url = server_url.rstrip("/")
        self.timeout = timeout
        self.default_confidence = default_confidence

    def health(self) -> dict:
        """Check if the YOLO-E server is reachable and model is loaded."""
        try:
            r = httpx.get(f"{self.server_url}/health", timeout=5.0)
            if r.status_code == 200:
                return {"available": True, **r.json()}
            return {"available": False, "status_code": r.status_code}
        except Exception as e:
            return {"available": False, "error": str(e)}

    def segment(self, jpeg_bytes: bytes, prompt: str = "object",
                confidence: float | None = None) -> dict:
        """Send a JPEG frame to YOLO-E /segment and return detections."""
        conf = confidence if confidence is not None else self.default_confidence
        try:
            r = httpx.post(
                f"{self.server_url}/segment",
                files={"image_file": ("frame.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
                data={"text_prompt": prompt, "confidence": str(conf)},
                timeout=self.timeout,
            )
            if r.status_code == 200:
                return {"success": True, **r.json()}
            return {"success": False, "error": f"HTTP {r.status_code}", "detail": r.text}
        except Exception as e:
            logger.warning("YOLO segment failed: %s", e)
            return {"success": False, "error": str(e)}

    def segment_visualization(self, jpeg_bytes: bytes, prompt: str = "object",
                              confidence: float | None = None) -> bytes | None:
        """Send a JPEG frame to YOLO-E and return an annotated JPEG image."""
        conf = confidence if confidence is not None else self.default_confidence
        try:
            r = httpx.post(
                f"{self.server_url}/segment_visualization",
                files={"image_file": ("frame.jpg", io.BytesIO(jpeg_bytes), "image/jpeg")},
                data={"text_prompt": prompt, "confidence": str(conf)},
                timeout=self.timeout,
            )
            if r.status_code == 200 and "image" in r.headers.get("content-type", ""):
                return r.content
            return None
        except Exception as e:
            logger.warning("YOLO segment_viz failed: %s", e)
            return None
