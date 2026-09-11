from collections.abc import Iterator
from dataclasses import dataclass
from threading import Condition, Event, Lock, Thread
from typing import Any


@dataclass
class CameraSource:
    stop_event: Event
    frame_ready: Event
    condition: Condition
    subscribers: int = 0
    frame: bytes | None = None
    version: int = 0
    inference: Any | None = None


class CameraStreamRegistry:
    def __init__(self) -> None:
        self._lock = Lock()
        self._sources: dict[str, CameraSource] = {}

    def subscribe(
        self, camera_id: str, preview: bool, inference: Any | None
    ) -> CameraSource:
        with self._lock:
            source = self._sources.get(camera_id)
            if source is None:
                source = CameraSource(Event(), Event(), Condition(Lock()))
                self._sources[camera_id] = source
                Thread(
                    target=self._capture,
                    args=(camera_id, source),
                    name=f"camera-{camera_id}",
                    daemon=True,
                ).start()
            source.subscribers += 1
            if not preview and inference is not None:
                source.inference = inference
            return source

    def unsubscribe(self, camera_id: str, source: CameraSource) -> None:
        with self._lock:
            source.subscribers -= 1
            if source.subscribers <= 0 and self._sources.get(camera_id) is source:
                self._sources.pop(camera_id, None)
                source.stop_event.set()
                with source.condition:
                    source.condition.notify_all()

    def close(
        self, selected_ids: set[str] | None = None, previews_only: bool = False
    ) -> None:
        with self._lock:
            sources = list(self._sources.items())
        for camera_id, source in sources:
            if selected_ids is not None and camera_id in selected_ids:
                continue
            if previews_only and source.inference is not None:
                continue
            source.stop_event.set()

    @staticmethod
    def _capture(camera_id: str, source: CameraSource) -> None:
        import cv2

        camera = cv2.VideoCapture(camera_index(camera_id))
        if not camera.isOpened():
            source.stop_event.set()
            source.frame_ready.set()
            with source.condition:
                source.condition.notify_all()
            camera.release()
            return
        try:
            while not source.stop_event.is_set():
                success, frame = camera.read()
                if not success:
                    break
                if source.inference is not None:
                    frame = source.inference.annotate(camera_id, frame)
                success, encoded = cv2.imencode(".jpg", frame)
                if not success:
                    continue
                with source.condition:
                    source.frame = encoded.tobytes()
                    source.version += 1
                    source.frame_ready.set()
                    source.condition.notify_all()
        finally:
            source.stop_event.set()
            with source.condition:
                source.condition.notify_all()
            camera.release()


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
    source = registry.subscribe(camera_id, preview, inference)
    version = -1
    try:
        while not source.stop_event.is_set():
            with source.condition:
                source.condition.wait_for(
                    lambda current_version=version: (
                        source.version != current_version or source.stop_event.is_set()
                    )
                )
                if source.frame is None:
                    continue
                version = source.version
                frame = source.frame
            yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + frame + b"\r\n"
    finally:
        registry.unsubscribe(camera_id, source)
