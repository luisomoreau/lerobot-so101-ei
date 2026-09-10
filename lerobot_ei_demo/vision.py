import os
import re
import time
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Event, Lock, Thread
from typing import Any

from lerobot_ei_demo import ingestion
from lerobot_ei_demo.edge_impulse import host_architecture, is_compatible


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    path: str
    compatible: bool


@dataclass
class CameraInference:
    camera_id: str
    model_id: str | None = None
    enabled: bool = False
    confidence: float = 0.5
    status: str = "idle"
    error: str | None = None
    inference_ms: float | None = None
    upload_enabled: bool = False
    upload_interval_s: float = 5.0
    last_upload_at: float | None = None
    last_upload_status: str | None = None
    upload_error: str | None = None


@dataclass
class RunnerState:
    runner: Any
    width: int
    height: int
    resize_mode: str
    grayscale: bool
    centroid_only: bool
    lock: Lock


def _result_items(result: dict[str, Any]) -> list[dict[str, Any]]:
    output = result.get("result") or result
    boxes = output.get("bounding_boxes") or output.get("detections") or []
    if boxes:
        return [box for box in boxes if isinstance(box, dict)]
    centroids = output.get("centroids") or []
    return [
        {
            "label": centroid.get("label", "object"),
            "value": centroid.get("value", centroid.get("confidence", 0)),
            "x": centroid.get("x", centroid.get("cx", 0)),
            "y": centroid.get("y", centroid.get("cy", 0)),
            "width": 0,
            "height": 0,
        }
        for centroid in centroids
        if isinstance(centroid, dict)
    ]


def _map_point(
    x: float,
    y: float,
    frame_width: int,
    frame_height: int,
    input_width: int,
    input_height: int,
    resize_mode: str,
) -> tuple[int, int]:
    mode = "squash" if resize_mode == "not-reported" else resize_mode
    if mode == "fit-shortest":
        scale = max(input_width / frame_width, input_height / frame_height)
        resized_width = frame_width * scale
        resized_height = frame_height * scale
        crop_x = (resized_width - input_width) / 2
        crop_y = (resized_height - input_height) / 2
        return round((x + crop_x) / scale), round((y + crop_y) / scale)
    if mode == "fit-longest":
        scale = min(input_width / frame_width, input_height / frame_height)
        pad_x = (input_width - frame_width * scale) / 2
        pad_y = (input_height - frame_height * scale) / 2
        return round((x - pad_x) / scale), round((y - pad_y) / scale)
    return round(x * frame_width / input_width), round(y * frame_height / input_height)


def _map_detection(
    detection: dict[str, Any], frame_shape: tuple[int, ...], runner: RunnerState
) -> dict[str, Any]:
    frame_height, frame_width = frame_shape[:2]
    values = [detection.get(key, 0) for key in ("x", "y", "width", "height")]
    if all(isinstance(value, (int, float)) and 0 <= value <= 1 for value in values):
        values = [
            values[0] * runner.width,
            values[1] * runner.height,
            values[2] * runner.width,
            values[3] * runner.height,
        ]
    x, y = _map_point(
        float(values[0]),
        float(values[1]),
        frame_width,
        frame_height,
        runner.width,
        runner.height,
        runner.resize_mode,
    )
    right, bottom = _map_point(
        float(values[0]) + float(values[2]),
        float(values[1]) + float(values[3]),
        frame_width,
        frame_height,
        runner.width,
        runner.height,
        runner.resize_mode,
    )
    if runner.centroid_only:
        x = round((x + right) / 2)
        y = round((y + bottom) / 2)
        return {
            "label": str(detection.get("label") or "object"),
            "confidence": float(detection.get("value", detection.get("confidence", 0))),
            "x": x,
            "y": y,
            "width": 0,
            "height": 0,
        }
    return {
        "label": str(detection.get("label") or "object"),
        "confidence": float(detection.get("value", detection.get("confidence", 0))),
        "x": x,
        "y": y,
        "width": max(0, right - x),
        "height": max(0, bottom - y),
    }


def _mask_unused_regions(frame: Any, runner: RunnerState) -> Any:
    import cv2

    if runner.resize_mode not in {"fit-shortest"}:
        return frame
    frame_height, frame_width = frame.shape[:2]
    source_aspect = frame_width / frame_height
    model_aspect = runner.width / runner.height
    overlay = frame.copy()
    if source_aspect > model_aspect:
        used_width = round(frame_height * model_aspect)
        left = (frame_width - used_width) // 2
        right = left + used_width
        cv2.rectangle(overlay, (0, 0), (left, frame_height), (128, 128, 128), -1)
        cv2.rectangle(
            overlay,
            (right, 0),
            (frame_width, frame_height),
            (128, 128, 128),
            -1,
        )
    elif source_aspect < model_aspect:
        used_height = round(frame_width / model_aspect)
        top = (frame_height - used_height) // 2
        bottom = top + used_height
        cv2.rectangle(overlay, (0, 0), (frame_width, top), (128, 128, 128), -1)
        cv2.rectangle(
            overlay,
            (0, bottom),
            (frame_width, frame_height),
            (128, 128, 128),
            -1,
        )
    return cv2.addWeighted(overlay, 0.6, frame, 0.4, 0)


class ModelCatalog:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(os.getenv("EI_MODELS_DIR", "models"))

    def list(self) -> list[dict[str, str | bool]]:
        if not self.root.exists():
            return []
        return [asdict(self._model(path)) for path in sorted(self.root.glob("*.eim"))]

    def find(self, model_id: str) -> dict[str, str | bool] | None:
        return next((model for model in self.list() if model["id"] == model_id), None)

    @staticmethod
    def is_fomo(model: dict[str, str | bool]) -> bool:
        return "fomo" in str(model["id"]).lower()

    @staticmethod
    def _model(path: Path) -> ModelInfo:
        return ModelInfo(
            id=path.name,
            name=path.stem.replace("-", " "),
            path=str(path),
            compatible=is_compatible(path.name),
        )


class InferenceService:
    """Tracks which Edge Impulse model is bound to each camera stream."""

    def __init__(self, catalog: ModelCatalog, app_config: Any | None = None) -> None:
        self.catalog = catalog
        self.app_config = app_config
        self._lock = Lock()
        self._assignments: dict[str, CameraInference] = {}
        self._runners: dict[str, RunnerState] = {}
        self._last_frames: dict[str, Any] = {}
        self._last_detections: dict[str, list[dict[str, Any]]] = {}
        self._last_model: dict[str, dict[str, Any]] = {}
        self._upload_stop = Event()
        self._upload_thread = Thread(
            target=self._upload_loop, name="ei-upload", daemon=True
        )
        self._upload_thread.start()

    def status(self) -> dict[str, object]:
        with self._lock:
            assignments = [asdict(item) for item in self._assignments.values()]
        return {
            "architecture": host_architecture(),
            "models": self.catalog.list(),
            "cameras": assignments,
        }

    def assign(
        self,
        camera_id: str,
        model_id: str | None,
        enabled: bool,
        confidence: float,
    ) -> dict[str, object]:
        if model_id is not None:
            model = self.catalog.find(model_id)
            if model is None:
                raise FileNotFoundError(f"Model not found: {model_id}")
            if enabled and not model["compatible"]:
                raise ValueError(
                    f"Model {model_id} is not built for {host_architecture()['label']}"
                )
        elif enabled:
            raise ValueError("Select a model before enabling inference")
        with self._lock:
            self._assignments[camera_id] = CameraInference(
                camera_id=camera_id,
                model_id=model_id,
                enabled=enabled,
                confidence=confidence,
                status="ready" if enabled else "idle",
            )
        return self.status()

    def clear(self, camera_id: str | None = None) -> dict[str, object]:
        with self._lock:
            if camera_id is None:
                self._assignments.clear()
                runners = list(self._runners.values())
                self._runners.clear()
                self._last_frames.clear()
                self._last_detections.clear()
                self._last_model.clear()
            else:
                self._assignments.pop(camera_id, None)
                self._last_frames.pop(camera_id, None)
                self._last_detections.pop(camera_id, None)
                self._last_model.pop(camera_id, None)
                runners = []
        for runner in runners:
            runner.runner.stop()
        return self.status()

    def set_upload(
        self, camera_id: str, enabled: bool, interval_s: float | None = None
    ) -> dict[str, object]:
        with self._lock:
            assignment = self._assignments.setdefault(
                camera_id, CameraInference(camera_id=camera_id)
            )
            assignment.upload_enabled = enabled
            if interval_s is not None:
                assignment.upload_interval_s = max(1.0, float(interval_s))
            if not enabled:
                assignment.last_upload_status = None
                assignment.upload_error = None
        return self.status()

    def upload_now(self, camera_id: str) -> dict[str, object]:
        with self._lock:
            frame = self._last_frames.get(camera_id)
            detections = list(self._last_detections.get(camera_id) or [])
            model_meta = self._last_model.get(camera_id) or {}
        if frame is None:
            raise RuntimeError(
                "No recent frame available to upload for this camera yet"
            )
        ei_config = self.app_config.get_edge_impulse() if self.app_config else {}
        api_key = str(ei_config.get("api_key") or "")
        if not api_key:
            raise RuntimeError("Connect an Edge Impulse project before uploading data")
        import cv2

        ok, buffer = cv2.imencode(".jpg", frame)
        if not ok:
            raise RuntimeError("Failed to encode frame for upload")
        image_bytes = buffer.tobytes()
        safe_camera_id = re.sub(r"[^A-Za-z0-9_-]+", "-", camera_id)
        filename = f"{safe_camera_id}.{uuid.uuid4().hex}.jpg"
        is_object_detection = (
            bool(detections)
            and not model_meta.get("is_fomo")
            and not model_meta.get("centroid_only")
        )
        bounding_boxes = (
            [
                {
                    "label": str(item["label"]),
                    "x": int(item["x"]),
                    "y": int(item["y"]),
                    "width": int(item["width"]),
                    "height": int(item["height"]),
                }
                for item in detections
            ]
            if is_object_detection
            else None
        )
        try:
            ingestion.upload_files(
                api_key,
                "training",
                [(filename, image_bytes, "image/jpeg")],
                no_label=True,
                metadata={"source": f"SO101-{safe_camera_id}-camera"},
                bounding_boxes=bounding_boxes,
            )
        except ingestion.IngestionError as error:
            with self._lock:
                assignment = self._assignments.setdefault(
                    camera_id, CameraInference(camera_id=camera_id)
                )
                assignment.last_upload_at = time.time()
                assignment.last_upload_status = "error"
                assignment.upload_error = str(error)
            raise RuntimeError(str(error)) from error
        with self._lock:
            assignment = self._assignments.setdefault(
                camera_id, CameraInference(camera_id=camera_id)
            )
            assignment.last_upload_at = time.time()
            assignment.last_upload_status = "ok"
            assignment.upload_error = None
        return self.status()

    def _upload_loop(self) -> None:
        while not self._upload_stop.is_set():
            due = []
            with self._lock:
                now = time.time()
                for camera_id, assignment in self._assignments.items():
                    if not assignment.upload_enabled:
                        continue
                    last = assignment.last_upload_at or 0
                    if now - last >= assignment.upload_interval_s:
                        due.append(camera_id)
            for camera_id in due:
                try:
                    self.upload_now(camera_id)
                except Exception as error:  # noqa: BLE001 - keep the loop alive
                    with self._lock:
                        assignment = self._assignments.get(camera_id)
                        if assignment is not None:
                            assignment.last_upload_at = time.time()
                            assignment.last_upload_status = "error"
                            assignment.upload_error = str(error)
            self._upload_stop.wait(1.0)

    def _runner_for(self, model: dict[str, str | bool]) -> RunnerState:
        model_id = str(model["id"])
        with self._lock:
            existing = self._runners.get(model_id)
        if existing is not None:
            return existing
        from edge_impulse_linux.image import ImageImpulseRunner

        runner = ImageImpulseRunner(str(model["path"]))
        info = runner.init()
        parameters = info["model_parameters"]
        state = RunnerState(
            runner=runner,
            width=int(parameters["image_input_width"]),
            height=int(parameters["image_input_height"]),
            resize_mode=str(parameters.get("image_resize_mode", "not-reported")),
            grayscale=int(parameters.get("image_channel_count", 3)) == 1,
            centroid_only=ModelCatalog.is_fomo(model),
            lock=Lock(),
        )
        with self._lock:
            self._runners[model_id] = state
        return state

    def annotate(self, camera_id: str, frame: Any) -> Any:
        import cv2

        with self._lock:
            self._last_frames[camera_id] = frame.copy()
            assignment = self._assignments.get(camera_id)
            if assignment is None or not assignment.enabled or not assignment.model_id:
                self._last_detections.pop(camera_id, None)
                self._last_model.pop(camera_id, None)
                return frame
            model = self.catalog.find(assignment.model_id)
        if model is None:
            return frame
        try:
            runner = self._runner_for(model)
            rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            with runner.lock:
                features, _ = (
                    runner.runner.get_features_from_image_auto_studio_settings(
                        rgb_frame
                    )
                )
                inference_started = time.perf_counter()
                result = runner.runner.classify(features)
                inference_ms = (time.perf_counter() - inference_started) * 1000
            detections = [
                _map_detection(item, frame.shape, runner)
                for item in _result_items(result)
                if float(item.get("value", item.get("confidence", 0)))
                >= assignment.confidence
            ]
            with self._lock:
                self._last_frames[camera_id] = frame.copy()
                self._last_detections[camera_id] = detections
                self._last_model[camera_id] = {
                    "model_id": assignment.model_id,
                    "is_fomo": ModelCatalog.is_fomo(model),
                    "centroid_only": runner.centroid_only,
                }
            frame = _mask_unused_regions(frame, runner)
            for detection in detections:
                x, y = detection["x"], detection["y"]
                label = f"{detection['label']} {detection['confidence']:.0%}"
                if detection["width"] and detection["height"]:
                    cv2.rectangle(
                        frame,
                        (x, y),
                        (x + detection["width"], y + detection["height"]),
                        (40, 190, 120),
                        2,
                    )
                    text_y = max(18, y - 6)
                else:
                    cv2.circle(frame, (x, y), 8, (40, 190, 120), -1)
                    text_y = max(18, y - 12)
                cv2.putText(
                    frame,
                    label,
                    (max(4, x), text_y),
                    cv2.FONT_HERSHEY_SIMPLEX,
                    0.55,
                    (40, 190, 120),
                    2,
                    cv2.LINE_AA,
                )
            cv2.putText(
                frame,
                f"Inference {inference_ms:.1f} ms",
                (10, frame.shape[0] - 12),
                cv2.FONT_HERSHEY_SIMPLEX,
                0.55,
                (40, 190, 120),
                2,
                cv2.LINE_AA,
            )
            with self._lock:
                current = self._assignments.get(camera_id)
                if current is not None:
                    current.status = "running"
                    current.error = None
                    current.inference_ms = round(inference_ms, 1)
        except Exception as error:  # noqa: BLE001 - keep the camera stream alive
            with self._lock:
                current = self._assignments.get(camera_id)
                if current is not None:
                    current.status = "error"
                    current.error = str(error)
        return frame
