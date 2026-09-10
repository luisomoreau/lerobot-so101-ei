import numpy as np

from lerobot_ei_demo.game import Circle, GameService


def test_start_creates_requested_circle_count_and_duration() -> None:
    game = GameService()

    status = game.start("opencv:0", circle_count=4, duration_s=30)

    assert status["active"] is True
    assert status["finished"] is False
    assert status["camera_id"] == "opencv:0"
    assert status["duration_s"] == 30
    assert status["total"] == 4
    assert status["score"] == 0
    assert len(status["circles"]) == 4
    for circle in status["circles"]:
        assert 0 <= circle["x"] <= 1
        assert 0 <= circle["y"] <= 1
        assert circle["hit"] is False


def test_circle_count_is_clamped_to_valid_range() -> None:
    game = GameService()

    status = game.start("opencv:0", circle_count=99, duration_s=60)

    assert status["total"] == 8  # MAX_CIRCLES


def test_apply_marks_circle_hit_when_detection_center_within_radius() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=1, duration_s=60)
    with game._lock:
        game._circles = [Circle(id=0, x=0.5, y=0.5, radius=0.1)]

    frame = np.zeros((100, 100, 3), dtype="uint8")
    detections = [{"x": 45, "y": 45, "width": 10, "height": 10}]

    game.apply("opencv:0", frame, detections)

    status = game.status()
    assert status["score"] == 1
    assert status["circles"][0]["hit"] is True


def test_apply_ignores_detections_outside_circle_radius() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=1, duration_s=60)
    with game._lock:
        game._circles = [Circle(id=0, x=0.5, y=0.5, radius=0.05)]

    frame = np.zeros((100, 100, 3), dtype="uint8")
    detections = [{"x": 0, "y": 0, "width": 4, "height": 4}]

    game.apply("opencv:0", frame, detections)

    status = game.status()
    assert status["score"] == 0
    assert status["circles"][0]["hit"] is False


def test_status_finishes_once_every_circle_is_hit() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=1, duration_s=60)
    with game._lock:
        game._circles = [Circle(id=0, x=0.5, y=0.5, radius=0.1, hit=True)]

    status = game.status()

    assert status["active"] is False
    assert status["finished"] is True
    assert status["score"] == 1


def test_status_finishes_once_time_expires() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=3, duration_s=60)
    with game._lock:
        game._started_at -= 61

    status = game.status()

    assert status["active"] is False
    assert status["finished"] is True
    assert status["remaining_s"] == 0.0


def test_stop_clears_the_active_game() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=2, duration_s=60)

    status = game.stop()

    assert status == {"active": False, "finished": False}


def test_apply_is_a_noop_for_a_different_camera() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=1, duration_s=60)
    with game._lock:
        game._circles = [Circle(id=0, x=0.5, y=0.5, radius=0.1)]

    frame = np.zeros((100, 100, 3), dtype="uint8")
    game.apply("opencv:1", frame, [{"x": 50, "y": 50, "width": 0, "height": 0}])

    assert game.status()["score"] == 0
