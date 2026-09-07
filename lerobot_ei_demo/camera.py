from collections.abc import Iterator
from threading import Event, Lock
from typing import Any


class CameraStreamRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._streams: dict[str, list[tuple[bool, Event]]] = {}

    def register(self, camera_id: str, preview: bool) -> Event:
        stop_event = Event()
        with self._lock:
            self._streams.setdefault(camera_id, []).append((preview, stop_event))
        return stop_event

    def unregister(self, camera_id: str, stop_event: Event) -> None:
        with self._lock:
            streams = self._streams.get(camera_id, [])
            remaining = [entry for entry in streams if entry[1] is not stop_event]
            if remaining:
                self._streams[camera_id] = remaining
            else:
                self._streams.pop(camera_id, None)

    def close(
        self, selected_ids: set[str] | None = None, previews_only: bool = False
    ) -> None:
        with self._lock:
            streams = list(self._streams.items())
        for camera_id, entries in streams:
            if selected_ids is not None and camera_id in selected_ids:
                continue
            for preview, stop_event in entries:
                if not previews_only or preview:
                    stop_event.set()


def camera_index(camera_id: str) -> int:
    prefix, _, value = camera_id.partition(":")
    if prefix != "opencv" or not value.isdigit():
        raise ValueError(f"Unsupported camera id: {camera_id}")
    return int(value)


def mjpeg_stream(
    camera_id: str,
    registry: CameraStreamRegistry,
    preview: bool = False,
    inference: Any | None = None,
) -> Iterator[bytes]:
    import cv2

    stop_event = registry.register(camera_id, preview)
    camera = cv2.VideoCapture(camera_index(camera_id))
    if not camera.isOpened():
        registry.unregister(camera_id, stop_event)
        camera.release()
        raise RuntimeError(f"Unable to open camera: {camera_id}")
    try:
        while not stop_event.is_set():
            success, frame = camera.read()
            if not success:
                break
            if inference is not None and not preview:
                frame = inference.annotate(camera_id, frame)
            success, encoded = cv2.imencode(".jpg", frame)
            if success:
                yield (
                    b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                    + encoded.tobytes()
                    + b"\r\n"
                )
    finally:
        camera.release()
        registry.unregister(camera_id, stop_event)
