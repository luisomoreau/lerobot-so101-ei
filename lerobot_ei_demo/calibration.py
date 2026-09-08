import time
from dataclasses import asdict, dataclass
from threading import Event, Lock, Thread, current_thread


@dataclass
class CalibrationState:
    status: str = "idle"
    role: str | None = None
    phase: str | None = None
    positions: dict[str, int] | None = None
    ranges: dict[str, dict[str, int]] | None = None
    message: str = "Ready"
    error: str | None = None


class CalibrationService:
    def __init__(self) -> None:
        self._lock = Lock()
        self._bus_lock = Lock()
        self._stop = Event()
        self._thread: Thread | None = None
        self._device = None
        self._state = CalibrationState()
        self._mins: dict[str, int] = {}
        self._maxes: dict[str, int] = {}
        self._homings: dict[str, int] = {}

    def snapshot(self) -> dict:
        with self._lock:
            return asdict(self._state)

    @property
    def active(self) -> bool:
        with self._lock:
            return bool(self._thread and self._thread.is_alive())

    def start(self, role: str, port: str) -> dict:
        if role not in {"leader", "follower"}:
            raise ValueError("Calibration role must be leader or follower")
        with self._lock:
            if self._thread and self._thread.is_alive():
                raise RuntimeError("Calibration is already running")
            self._stop.clear()
            self._mins = {}
            self._maxes = {}
            self._homings = {}
            self._state = CalibrationState(
                status="running",
                role=role,
                phase="center",
                positions={},
                ranges={},
                message="Move the arm to its center position, then capture center.",
            )
            self._thread = Thread(
                target=self._run,
                args=(role, port),
                name="lerobot-calibration",
                daemon=True,
            )
            self._thread.start()
            return asdict(self._state)

    def capture_center(self) -> dict:
        with self._lock:
            self._require_phase("center")
            device = self._device
            if device is None:
                raise RuntimeError("Calibration device is still connecting")
        with self._bus_lock:
            homings = device.bus.set_half_turn_homings()
        with self._lock:
            self._homings = {name: int(value) for name, value in homings.items()}
            self._state.phase = "range"
            self._state.message = "Move every joint through its full safe range, then save calibration."
            self._state.positions = self._read_positions(device)
        return asdict(self._state)

    def finish(self) -> dict:
        with self._lock:
            self._require_phase("range")
            device = self._device
            if device is None:
                raise RuntimeError("Calibration device is not connected")
            mins = dict(self._mins)
            maxes = dict(self._maxes)
        motors = device.bus.motors
        from lerobot.motors import MotorCalibration

        calibration = {}
        for name, motor in motors.items():
            calibration[name] = MotorCalibration(
                id=motor.id,
                drive_mode=0,
                homing_offset=self._homings.get(name, 0),
                range_min=mins.get(name, 0),
                range_max=maxes.get(name, 4095),
            )
        with self._bus_lock:
            device.bus.write_calibration(calibration)
            device.calibration = calibration
            device._save_calibration()
        self.stop()
        with self._lock:
            self._state.status = "complete"
            self._state.phase = None
            self._state.ranges = {
                name: {"min": item.range_min, "max": item.range_max}
                for name, item in calibration.items()
            }
            self._state.message = "Calibration saved to the official LeRobot path."
        return asdict(self._state)

    def stop(self) -> dict:
        self._stop.set()
        thread = self._thread
        if thread and thread is not current_thread():
            thread.join(timeout=2)
        with self._lock:
            device = self._device
            self._device = None
            self._thread = None
            if self._state.status == "running":
                self._state.status = "stopped"
                self._state.phase = None
                self._state.message = "Calibration stopped without saving."
        if device is not None:
            device.bus.disconnect()
        return self.snapshot()

    def _run(self, role: str, port: str) -> None:
        try:
            if role == "leader":
                from lerobot.teleoperators.so_leader import SO101LeaderConfig
                from lerobot.teleoperators.utils import make_teleoperator_from_config

                device = make_teleoperator_from_config(
                    SO101LeaderConfig(port=port, id="SO101")
                )
            else:
                from lerobot.robots.so_follower import SO101FollowerConfig
                from lerobot.robots.utils import make_robot_from_config

                device = make_robot_from_config(
                    SO101FollowerConfig(port=port, id="SO101")
                )
            device.bus.connect()
            device.bus.disable_torque()
            with self._lock:
                self._device = device
            while not self._stop.is_set():
                positions = self._read_positions(device)
                with self._lock:
                    self._state.positions = positions
                    if self._state.phase == "range":
                        for name, value in positions.items():
                            self._mins[name] = min(value, self._mins.get(name, value))
                            self._maxes[name] = max(value, self._maxes.get(name, value))
                        self._state.ranges = {
                            name: {"min": self._mins[name], "max": self._maxes[name]}
                            for name in self._mins
                        }
                time.sleep(0.05)
        except (ImportError, KeyError, OSError, RuntimeError, ValueError) as error:
            with self._lock:
                self._state.status = "error"
                self._state.error = str(error)
                self._state.message = "Calibration failed."
                device = self._device
                self._device = None
            if device is not None:
                device.bus.disconnect()

    def _read_positions(self, device) -> dict[str, int]:
        with self._bus_lock:
            values = device.bus.sync_read("Present_Position", normalize=False)
        return {name: int(value) for name, value in values.items()}

    def _require_phase(self, phase: str) -> None:
        if self._state.status != "running" or self._state.phase != phase:
            raise RuntimeError(f"Calibration is not in the {phase} phase")
