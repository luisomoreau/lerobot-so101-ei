"""A small gamified challenge: place objects inside randomly placed circles.

Circles are stored as fractions (0..1) of the frame width/height so they can be
drawn onto any camera resolution, and reused verbatim by the frontend to
render a matching overlay without needing the raw frame size.
"""

import random
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

DEFAULT_DURATION_S = 60.0
DEFAULT_CIRCLE_COUNT = 3
MIN_CIRCLES = 1
MAX_CIRCLES = 8
CIRCLE_RADIUS_FRAC = 0.09
RED_BGR = (60, 60, 220)
GREEN_BGR = (90, 200, 90)


@dataclass
class Circle:
    id: int
    x: float
    y: float
    radius: float
    hit: bool = False


class GameService:
    """Tracks a single active "place the object" game, one camera at a time."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._camera_id: str | None = None
        self._circles: list[Circle] = []
        self._duration_s = DEFAULT_DURATION_S
        self._started_at = 0.0
        self._finished = False

    def start(
        self,
        camera_id: str,
        circle_count: int = DEFAULT_CIRCLE_COUNT,
        duration_s: float = DEFAULT_DURATION_S,
    ) -> dict[str, object]:
        count = max(MIN_CIRCLES, min(MAX_CIRCLES, int(circle_count)))
        duration = max(5.0, float(duration_s))
        rng = random.Random()
        margin = CIRCLE_RADIUS_FRAC * 1.4
        circles = [
            Circle(
                id=i,
                x=rng.uniform(margin, 1 - margin),
                y=rng.uniform(margin, 1 - margin),
                radius=CIRCLE_RADIUS_FRAC,
            )
            for i in range(count)
        ]
        with self._lock:
            self._camera_id = camera_id
            self._circles = circles
            self._duration_s = duration
            self._started_at = time.time()
            self._finished = False
        return self.status()

    def stop(self) -> dict[str, object]:
        with self._lock:
            self._camera_id = None
            self._circles = []
            self._finished = False
        return self.status()

    def status(self) -> dict[str, object]:
        with self._lock:
            if self._camera_id is None:
                return {"active": False, "finished": False}
            remaining = max(0.0, self._duration_s - (time.time() - self._started_at))
            all_hit = bool(self._circles) and all(c.hit for c in self._circles)
            finished = self._finished or remaining <= 0 or all_hit
            self._finished = finished
            score = sum(1 for c in self._circles if c.hit)
            return {
                "active": not finished,
                "finished": finished,
                "camera_id": self._camera_id,
                "circles": [
                    {"id": c.id, "x": c.x, "y": c.y, "radius": c.radius, "hit": c.hit}
                    for c in self._circles
                ],
                "remaining_s": round(remaining, 1),
                "duration_s": self._duration_s,
                "score": score,
                "total": len(self._circles),
            }

    def apply(
        self, camera_id: str, frame: Any, detections: list[dict[str, Any]]
    ) -> Any:
        """Draw the active game's circles onto `frame`, marking hits from `detections`."""
        import cv2

        with self._lock:
            if self._camera_id != camera_id or self._finished or not self._circles:
                return frame
            frame_height, frame_width = frame.shape[:2]
            min_dim = min(frame_width, frame_height)
            for detection in detections:
                cx = detection["x"] + detection.get("width", 0) / 2
                cy = detection["y"] + detection.get("height", 0) / 2
                for circle in self._circles:
                    if circle.hit:
                        continue
                    circle_cx = circle.x * frame_width
                    circle_cy = circle.y * frame_height
                    circle_r = circle.radius * min_dim
                    if (cx - circle_cx) ** 2 + (cy - circle_cy) ** 2 <= circle_r**2:
                        circle.hit = True
            for circle in self._circles:
                center = (round(circle.x * frame_width), round(circle.y * frame_height))
                radius = round(circle.radius * min_dim)
                color = GREEN_BGR if circle.hit else RED_BGR
                cv2.circle(frame, center, radius, color, 4)
        return frame
