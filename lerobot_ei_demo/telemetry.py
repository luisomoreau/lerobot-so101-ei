from collections import deque
from threading import Lock
from time import monotonic

JOINT_NAMES = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_roll",
    "gripper",
)


class TelemetryHub:
    def __init__(self, max_samples: int = 600) -> None:
        self._lock = Lock()
        self._samples: deque[dict[str, object]] = deque(maxlen=max_samples)

    def publish(self, joints: dict[str, object]) -> dict[str, object]:
        normalized = {
            name.removesuffix(".pos"): value for name, value in joints.items()
        }
        sample = {
            "type": "joint_update",
            "timestamp": monotonic(),
            "joints": {
                name: float(normalized[name])
                for name in JOINT_NAMES
                if name in normalized
            },
        }
        with self._lock:
            self._samples.append(sample)
        return sample

    def latest(self) -> dict[str, object] | None:
        with self._lock:
            return self._samples[-1] if self._samples else None

    def history(self) -> list[dict[str, object]]:
        with self._lock:
            return list(self._samples)
