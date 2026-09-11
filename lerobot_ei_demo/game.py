"""A small gamified challenge: place objects inside randomly placed circles.

Circles are stored as fractions (0..1) of the frame width/height so they can be
drawn onto any camera resolution, and reused verbatim by the frontend to
render a matching overlay without needing the raw frame size. Placement is
deferred until the first frame is available, so circles can be constrained to
the "active zone" the assigned model actually sees (see `_active_zone` in
`vision.py`) instead of the full, possibly-cropped, camera frame.
"""

import math
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
MAX_PLACEMENT_ATTEMPTS = 100
RED_BGR = (60, 60, 220)
GREEN_BGR = (90, 200, 90)
FULL_ZONE = (0.0, 0.0, 1.0, 1.0)


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
        self._circle_count = DEFAULT_CIRCLE_COUNT
        self._circles: list[Circle] = []
        self._placed = False
        self._duration_s = DEFAULT_DURATION_S
        self._started_at = 0.0
        self._finished = False

    def start(
        self,
        camera_id: str,
        circle_count: int = DEFAULT_CIRCLE_COUNT,
        duration_s: float = DEFAULT_DURATION_S,
    ) -> dict[str, object]:
        with self._lock:
            self._camera_id = camera_id
            self._circle_count = max(MIN_CIRCLES, min(MAX_CIRCLES, int(circle_count)))
            self._circles = []
            self._placed = False
            self._duration_s = max(5.0, float(duration_s))
            self._started_at = time.time()
            self._finished = False
        return self.status()

    def stop(self) -> dict[str, object]:
        with self._lock:
            self._camera_id = None
            self._circles = []
            self._placed = False
            self._finished = False
        return self.status()

    def status(self) -> dict[str, object]:
        with self._lock:
            if self._camera_id is None:
                return {"active": False, "finished": False}
            remaining = max(0.0, self._duration_s - (time.time() - self._started_at))
            all_hit = self._placed and all(c.hit for c in self._circles)
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
                "total": self._circle_count,
            }

    def apply(
        self,
        camera_id: str,
        frame: Any,
        detections: list[dict[str, Any]],
        zone: tuple[float, float, float, float] = FULL_ZONE,
    ) -> Any:
        """Draw the active game's circles onto `frame`, marking hits from `detections`.

        `zone` is the (x0, y0, x1, y1) fraction of the frame the assigned model
        actually sees; circles are only ever placed inside it.
        """
        import cv2

        with self._lock:
            if self._camera_id != camera_id or self._finished:
                return frame
            if not self._placed:
                self._circles = self._place_circles(zone)
                self._placed = True
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

    def _place_circles(self, zone: tuple[float, float, float, float]) -> list[Circle]:
        x0, y0, x1, y1 = zone
        width = x1 - x0
        height = y1 - y0
        radius = min(CIRCLE_RADIUS_FRAC, width / 2, height / 2)
        rng = random.Random()
        circles: list[Circle] = []
        for circle_id in range(self._circle_count):
            for _ in range(MAX_PLACEMENT_ATTEMPTS):
                x = rng.uniform(x0 + radius, x1 - radius)
                y = rng.uniform(y0 + radius, y1 - radius)
                if all(
                    (x - circle.x) ** 2 + (y - circle.y) ** 2
                    >= (radius + circle.radius) ** 2
                    for circle in circles
                ):
                    circles.append(Circle(id=circle_id, x=x, y=y, radius=radius))
                    break
            else:
                return self._circle_grid(zone)
        return circles

    def _circle_grid(self, zone: tuple[float, float, float, float]) -> list[Circle]:
        """Fit the requested circles without overlap when random placement is crowded."""
        x0, y0, x1, y1 = zone
        width = x1 - x0
        height = y1 - y0
        columns = math.ceil(math.sqrt(self._circle_count * width / height))
        rows = math.ceil(self._circle_count / columns)
        radius = min(CIRCLE_RADIUS_FRAC, width / (2 * columns), height / (2 * rows))
        return [
            Circle(
                id=circle_id,
                x=x0 + ((circle_id % columns) + 0.5) * width / columns,
                y=y0 + (circle_id // columns + 0.5) * height / rows,
                radius=radius,
            )
            for circle_id in range(self._circle_count)
        ]
