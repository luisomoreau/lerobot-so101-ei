import json
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
                    if field in ("leader_port", "follower_port"):
                        _write_saved_port(field.removesuffix("_port"), value)
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
    try:
        from serial.tools import list_ports
    except ImportError:
        candidates = list(Path("/dev").glob("cu.usb*")) + list(
            Path("/dev").glob("tty.usb*")
        )
        return sorted({str(path) for path in candidates})
    return sorted(
        port.device
        for port in list_ports.comports()
        if any(
            port.device.lower().endswith(marker)
            or f"/{marker}" in port.device.lower()
            for marker in ("cu.usb", "ttyacm", "ttyusb")
        )
    )


def _read_saved_port(role: str) -> str | None:
    path = Path.home() / ".cache/huggingface/lerobot/ports" / f"{role}_port.txt"
    try:
        port = path.read_text().strip()
    except OSError:
        return None
    return port or None


def _write_saved_port(role: str, port: str) -> None:
    path = Path.home() / ".cache/huggingface/lerobot/ports" / f"{role}_port.txt"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"{port}\n", encoding="utf-8")


def import_calibration(role: str, contents: str) -> dict[str, str]:
    if role not in {"leader", "follower"}:
        raise ValueError("Calibration role must be leader or follower")
    try:
        payload = json.loads(contents)
    except json.JSONDecodeError as error:
        raise ValueError("Calibration file must contain valid JSON") from error
    if not isinstance(payload, dict):
        raise TypeError("Calibration file must contain a JSON object")

    relative_path = (
        "teleoperators/so_leader/SO101.json"
        if role == "leader"
        else "robots/so_follower/SO101.json"
    )
    path = Path.home() / ".cache/huggingface/lerobot/calibration" / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    temporary.chmod(0o600)
    temporary.replace(path)
    return {"role": role, "path": str(path)}


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
