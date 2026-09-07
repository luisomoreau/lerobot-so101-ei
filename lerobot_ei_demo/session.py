from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock


@dataclass
class SessionState:
    robot_type: str = "SO-101"
    leader_port: str | None = None
    follower_port: str | None = None
    camera_id: str | None = None
    operation: str = "idle"


class RobotSession:
    def __init__(self) -> None:
        self._lock = Lock()
        self._state = SessionState(
            leader_port=_read_saved_port("leader"),
            follower_port=_read_saved_port("follower"),
        )

    def snapshot(self) -> dict[str, str | None]:
        with self._lock:
            return asdict(self._state)

    def select(self, **values: str | None) -> dict[str, str | None]:
        with self._lock:
            for field, value in values.items():
                if value is not None and not hasattr(self._state, field):
                    raise ValueError(f"Unknown session field: {field}")
                if value is not None:
                    setattr(self._state, field, value)
            return asdict(self._state)

    def start(self, operation: str) -> dict[str, str | None]:
        with self._lock:
            if self._state.operation != "idle":
                raise RuntimeError(
                    f"Cannot start {operation}; {self._state.operation} is active"
                )
            self._state.operation = operation
            return asdict(self._state)

    def stop(self) -> dict[str, str | None]:
        with self._lock:
            self._state.operation = "idle"
            return asdict(self._state)


def discover_ports() -> list[str]:
    candidates = list(Path("/dev").glob("cu.usb*")) + list(
        Path("/dev").glob("tty.usb*")
    )
    return sorted({str(path) for path in candidates})


def _read_saved_port(role: str) -> str | None:
    path = Path.home() / ".cache/huggingface/lerobot/ports" / f"{role}_port.txt"
    try:
        port = path.read_text().strip()
    except OSError:
        return None
    return port or None


def calibration_status() -> dict[str, bool]:
    root = Path.home() / ".cache/huggingface/lerobot/calibration"
    return {
        "leader": (root / "teleoperators/so_leader/SO101.json").is_file(),
        "follower": (root / "robots/so_follower/SO101.json").is_file(),
    }


def discover_cameras() -> list[dict[str, str]]:
    try:
        import cv2
    except ImportError:
        return []

    cameras = []
    for index in range(8):
        camera = cv2.VideoCapture(index)
        if camera.isOpened():
            cameras.append(
                {
                    "id": f"opencv:{index}",
                    "name": f"Camera {index}",
                    "index": str(index),
                }
            )
        camera.release()
    return cameras
