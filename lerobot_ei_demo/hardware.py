import time
from threading import Event, Lock, Thread


class LeRobotController:
    def __init__(self, publish_joint_state=None) -> None:
        self._lock = Lock()
        self._stop_event = Event()
        self._thread: Thread | None = None
        self._robot = None
        self._teleop = None
        self._publish_joint_state = publish_joint_state

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self, leader_port: str, follower_port: str) -> None:
        from lerobot.robots.so_follower import SO101FollowerConfig
        from lerobot.robots.utils import make_robot_from_config
        from lerobot.teleoperators.so_leader import SO101LeaderConfig
        from lerobot.teleoperators.utils import make_teleoperator_from_config

        with self._lock:
            if self.active:
                raise RuntimeError("LeRobot teleoperation is already active")
            robot = make_robot_from_config(
                SO101FollowerConfig(port=follower_port, id="SO101")
            )
            teleop = make_teleoperator_from_config(
                SO101LeaderConfig(port=leader_port, id="SO101")
            )
            robot.connect(calibrate=False)
            try:
                teleop.connect(calibrate=False)
            except Exception:
                robot.disconnect()
                raise
            self._robot = robot
            self._teleop = teleop
            self._stop_event.clear()
            self._thread = Thread(
                target=self._run, name="lerobot-teleoperation", daemon=True
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lock:
            self._stop_event.set()
            thread = self._thread
        if thread is not None:
            thread.join(timeout=2)
        with self._lock:
            if self._teleop is not None:
                self._teleop.disconnect()
            if self._robot is not None:
                self._robot.disconnect()
            self._thread = None
            self._teleop = None
            self._robot = None

    def _run(self) -> None:
        while not self._stop_event.is_set():
            loop_start = time.perf_counter()
            action = self._teleop.get_action()
            self._robot.send_action(action)
            if self._publish_joint_state is not None:
                self._publish_joint_state(self._robot.get_observation())
            time.sleep(max(0, 1 / 60 - (time.perf_counter() - loop_start)))
