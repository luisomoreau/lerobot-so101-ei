import numpy as np

from lerobot_ei_demo.game import Circle, GameService


def test_start_then_first_apply_places_requested_circle_count() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=4, duration_s=30)
    frame = np.zeros((100, 100, 3), dtype="uint8")

    game.apply("opencv:0", frame, [])
    status = game.status()

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


def test_circles_are_placed_inside_the_given_zone() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=5, duration_s=60)
    frame = np.zeros((100, 100, 3), dtype="uint8")

    game.apply("opencv:0", frame, [], zone=(0.2, 0.3, 0.6, 0.7))

    for circle in game.status()["circles"]:
        assert 0.2 <= circle["x"] <= 0.6
        assert 0.3 <= circle["y"] <= 0.7


def test_circles_do_not_overlap() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=8, duration_s=60)
    frame = np.zeros((100, 100, 3), dtype="uint8")

    game.apply("opencv:0", frame, [])

    circles = game.status()["circles"]
    for index, circle in enumerate(circles):
        for other in circles[index + 1 :]:
            distance_squared = (circle["x"] - other["x"]) ** 2 + (
                circle["y"] - other["y"]
            ) ** 2
            assert distance_squared >= (circle["radius"] + other["radius"]) ** 2


def test_apply_marks_circle_hit_when_detection_center_within_radius() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=1, duration_s=60)
    with game._lock:
        game._circles = [Circle(id=0, x=0.5, y=0.5, radius=0.1)]
        game._placed = True

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
        game._placed = True

    frame = np.zeros((100, 100, 3), dtype="uint8")
    detections = [{"x": 0, "y": 0, "width": 4, "height": 4}]

    game.apply("opencv:0", frame, detections)

    status = game.status()
    assert status["score"] == 0
    assert status["circles"][0]["hit"] is False


def test_circle_returns_red_when_the_detection_leaves() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=2, duration_s=60)
    with game._lock:
        game._circles = [
            Circle(id=0, x=0.5, y=0.5, radius=0.1),
            Circle(id=1, x=0.1, y=0.1, radius=0.1),
        ]
        game._placed = True

    frame = np.zeros((100, 100, 3), dtype="uint8")
    game.apply("opencv:0", frame, [{"x": 45, "y": 45, "width": 10, "height": 10}])
    assert game.status()["score"] == 1

    game.apply("opencv:0", frame, [])
    assert game.status()["score"] == 0


def test_status_finishes_when_every_circle_is_occupied() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=1, duration_s=60)
    with game._lock:
        game._circles = [Circle(id=0, x=0.5, y=0.5, radius=0.1)]
        game._placed = True

    frame = np.zeros((100, 100, 3), dtype="uint8")
    game.apply("opencv:0", frame, [{"x": 45, "y": 45, "width": 10, "height": 10}])
    status = game.status()

    assert status["active"] is False
    assert status["finished"] is True
    assert status["score"] == 1
    assert status["outcome"] == "won"


def test_status_finishes_once_time_expires() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=3, duration_s=60)
    with game._lock:
        game._started_at -= 61

    status = game.status()

    assert status["active"] is False
    assert status["finished"] is True
    assert status["remaining_s"] == 0.0
    assert status["outcome"] == "lost"


def test_status_declares_a_complete_board_a_win_at_the_deadline() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=1, duration_s=60)
    with game._lock:
        game._circles = [Circle(id=0, x=0.5, y=0.5, radius=0.1, hit=True)]
        game._placed = True
        game._started_at -= 61

    status = game.status()

    assert status["finished"] is True
    assert status["outcome"] == "won"


def test_expired_game_keeps_the_final_circle_state_on_later_frames() -> None:
    game = GameService()
    game.start("opencv:0", circle_count=1, duration_s=60)
    with game._lock:
        game._circles = [Circle(id=0, x=0.5, y=0.5, radius=0.1, hit=True)]
        game._placed = True
        game._started_at -= 61

    frame = np.zeros((100, 100, 3), dtype="uint8")
    game.apply("opencv:0", frame, [])

    assert game.status()["score"] == 1


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
        game._placed = True

    frame = np.zeros((100, 100, 3), dtype="uint8")
    game.apply("opencv:1", frame, [{"x": 50, "y": 50, "width": 0, "height": 0}])

    assert game.status()["score"] == 0
