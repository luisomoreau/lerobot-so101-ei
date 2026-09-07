import json
import os
from pathlib import Path
from threading import Lock

DEFAULT_CONFIG_PATH = (
    Path(__file__).resolve().parent.parent / ".edge_impulse_config.json"
)


class AppConfig:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or Path(
            os.getenv("LEROBOT_EI_CONFIG", str(DEFAULT_CONFIG_PATH))
        )
        self._lock = Lock()

    def get_edge_impulse(self) -> dict[str, str | int | None]:
        with self._lock:
            data = self._read()
        edge_impulse = data.get("edge_impulse") or {}
        return {
            "api_key": str(edge_impulse.get("api_key") or ""),
            "project_id": edge_impulse.get("project_id"),
        }

    def save_edge_impulse(self, api_key: str, project_id: int | None = None) -> None:
        with self._lock:
            data = self._read()
            data["edge_impulse"] = {
                "api_key": api_key.strip(),
                "project_id": project_id,
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            temporary = self.path.with_suffix(".tmp")
            temporary.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
            temporary.chmod(0o600)
            temporary.replace(self.path)
            try:
                self.path.chmod(0o600)
            except OSError:
                pass

    def _read(self) -> dict:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return {}
