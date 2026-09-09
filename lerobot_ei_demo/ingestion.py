"""Edge Impulse Ingestion API client used to upload camera frames for retraining."""

import json
import uuid
from urllib import error as url_error
from urllib import request

INGESTION_BASE_URL = "https://ingestion.edgeimpulse.com"


class IngestionError(RuntimeError):
    """Raised when the Edge Impulse Ingestion API rejects or fails a request."""


def _multipart_body(files: list[tuple[str, bytes, str]]) -> tuple[bytes, str]:
    boundary = uuid.uuid4().hex
    body = bytearray()
    for filename, content, content_type in files:
        body += f"--{boundary}\r\n".encode()
        body += (
            f'Content-Disposition: form-data; name="data"; filename="{filename}"\r\n'
        ).encode()
        body += f"Content-Type: {content_type}\r\n\r\n".encode()
        body += content
        body += b"\r\n"
    body += f"--{boundary}--\r\n".encode()
    return bytes(body), boundary


def upload_files(
    api_key: str,
    category: str,
    files: list[tuple[str, bytes, str]],
    label: str | None = None,
    no_label: bool = False,
    timeout: int = 30,
) -> str:
    """Upload one or more files to an Edge Impulse project's ingestion endpoint.

    `files` is a list of `(filename, content, content_type)` tuples. `category`
    is one of "training", "testing", "validation", or "split".
    """
    body, boundary = _multipart_body(files)
    headers = {
        "x-api-key": api_key,
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    if no_label:
        headers["x-no-label"] = "1"
    elif label:
        headers["x-label"] = label
    req = request.Request(
        f"{INGESTION_BASE_URL}/api/{category}/files",
        data=body,
        headers=headers,
        method="POST",
    )
    try:
        with request.urlopen(req, timeout=timeout) as response:
            return response.read().decode("utf-8", "replace")
    except url_error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace") or str(error)
        raise IngestionError(
            f"Edge Impulse ingestion failed ({error.code}): {detail}"
        ) from error
    except Exception as error:
        raise IngestionError(f"Edge Impulse ingestion failed: {error}") from error


def object_detection_labels(
    image_filename: str, category: str, boxes: list[dict]
) -> bytes:
    """Build the Edge Impulse object detection `bounding_boxes.labels` payload."""
    payload = {
        "version": 1,
        "files": [
            {
                "path": image_filename,
                "category": category,
                "boundingBoxes": [
                    {
                        "label": str(box["label"]),
                        "x": int(box["x"]),
                        "y": int(box["y"]),
                        "width": int(box["width"]),
                        "height": int(box["height"]),
                    }
                    for box in boxes
                ],
            }
        ],
    }
    return json.dumps(payload).encode("utf-8")
