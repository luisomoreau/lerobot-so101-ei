import os
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock


@dataclass(frozen=True)
class ModelInfo:
    id: str
    name: str
    path: str


@dataclass
class InferenceState:
    status: str = "idle"
    model_id: str | None = None
    camera_id: str | None = None
    confidence: float = 0.5
    error: str | None = None


class ModelCatalog:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root or Path(os.getenv("EI_MODELS_DIR", "models"))

    def list(self) -> list[dict[str, str]]:
        if not self.root.exists():
            return []
        return [asdict(self._model(path)) for path in sorted(self.root.glob("*.eim"))]

    def find(self, model_id: str) -> ModelInfo | None:
        return next((model for model in self.list() if model["id"] == model_id), None)

    @staticmethod
    def _model(path: Path) -> ModelInfo:
        return ModelInfo(id=path.name, name=path.stem.replace("-", " "), path=str(path))


class InferenceService:
    def __init__(self, catalog: ModelCatalog) -> None:
        self.catalog = catalog
        self._lock = Lock()
        self._state = InferenceState()

    def status(self) -> dict[str, str | float | None]:
        with self._lock:
            return asdict(self._state)

    def start(
        self, model_id: str, camera_id: str, confidence: float
    ) -> dict[str, str | float | None]:
        model = self.catalog.find(model_id)
        if model is None:
            raise FileNotFoundError(f"Model not found: {model_id}")
        with self._lock:
            self._state = InferenceState(
                status="ready",
                model_id=model["id"],
                camera_id=camera_id,
                confidence=confidence,
            )
            return asdict(self._state)

    def stop(self) -> dict[str, str | float | None]:
        with self._lock:
            self._state = InferenceState()
            return asdict(self._state)
