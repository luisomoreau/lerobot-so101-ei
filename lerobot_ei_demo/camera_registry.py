import json
from pathlib import Path

from lerobot_ei_demo.session import discover_cameras


class CameraRegistry:
    def __init__(self, path: Path | None = None) -> None:
        self.path = (
            path or Path.home() / ".cache/huggingface/lerobot-ei-demo/cameras.json"
        )

    def all(self) -> list[dict[str, str | bool]]:
        manual = self._read()
        cameras = {
            camera["id"]: {
                **camera,
                "name": camera["name"],
                "manual": False,
                "selected": False,
            }
            for camera in discover_cameras()
        }
        for camera in manual:
            cameras[camera["id"]] = {
                **camera,
                "manual": True,
                "selected": camera.get("selected", True),
            }
        return list(cameras.values())

    def register(self, name: str, index: int) -> dict[str, str | bool]:
        camera = {
            "id": f"opencv:{index}",
            "name": name,
            "index": str(index),
            "selected": True,
        }
        manual = [entry for entry in self._read() if entry["id"] != camera["id"]]
        manual.append(camera)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(manual, indent=2) + "\n")
        return {**camera, "manual": True}

    def configure(
        self, cameras: list[dict[str, str | int | bool]]
    ) -> list[dict[str, str | bool]]:
        entries = []
        for camera in cameras:
            index = int(camera["index"])
            name = str(camera["name"]).strip()
            if not name:
                raise ValueError("Camera names cannot be empty")
            entries.append(
                {
                    "id": f"opencv:{index}",
                    "name": name,
                    "index": str(index),
                    "selected": bool(camera.get("selected", False)),
                }
            )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(entries, indent=2) + "\n")
        return [{**entry, "manual": True} for entry in entries]

    def remove(self, camera_id: str) -> bool:
        manual = self._read()
        remaining = [entry for entry in manual if entry["id"] != camera_id]
        if len(remaining) == len(manual):
            return False
        self.path.write_text(json.dumps(remaining, indent=2) + "\n")
        return True

    def _read(self) -> list[dict[str, str]]:
        try:
            data = json.loads(self.path.read_text())
        except (FileNotFoundError, OSError, json.JSONDecodeError):
            return []
        return [entry for entry in data if isinstance(entry, dict) and "id" in entry]
