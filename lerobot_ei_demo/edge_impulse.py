"""Edge Impulse Studio client used to list and download `.eim` models."""

import json
import platform
import threading
import time
import uuid
from pathlib import Path
from urllib import error as url_error
from urllib import request
from urllib.parse import unquote, urlencode

STUDIO_BASE_URL = "https://studio.edgeimpulse.com/v1"
ENGINES = {"tflite", "tflite-eon"}
MODEL_TYPES = {"float32", "int8"}
_ARCH_TOKENS = {
    "aarch64": ("aarch64", "arm64"),
    "armv7": ("armv7", "armhf"),
    "x86_64": ("x86_64", "x86-64", "amd64", "x64"),
}


class EdgeImpulseError(RuntimeError):
    """Raised when the Edge Impulse Studio API rejects or fails a request."""


def host_architecture() -> dict[str, str]:
    system = platform.system().lower()
    machine = platform.machine().lower()
    architecture = next(
        (
            name
            for name, tokens in _ARCH_TOKENS.items()
            if any(t in machine for t in tokens)
        ),
        machine or "unknown",
    )
    return {
        "system": system,
        "machine": machine,
        "architecture": architecture,
        "label": f"{system}/{architecture}",
    }


def is_compatible(text: str) -> bool:
    """Report whether a deployment target or `.eim` filename suits this host."""
    haystack = (text or "").lower()
    host = host_architecture()
    if host["system"] == "darwin" and not any(
        token in haystack for token in ("mac", "darwin", "osx")
    ):
        return False
    if host["system"] == "linux" and "linux" not in haystack:
        return False
    matched = {
        name
        for name, tokens in _ARCH_TOKENS.items()
        if any(token in haystack for token in tokens)
    }
    if not matched:
        return True
    if host["architecture"] in matched:
        return True
    # aarch64 hosts can execute armv7 builds, but never x86 builds.
    return host["architecture"] == "aarch64" and matched == {"armv7"}


def _headers(api_key: str) -> dict[str, str]:
    return {"x-api-key": api_key, "accept": "application/json"}


def _call(
    api_key: str,
    path: str,
    params: dict | None = None,
    json_body: dict | None = None,
    method: str = "GET",
    timeout: int = 60,
) -> dict:
    url = f"{STUDIO_BASE_URL}{path}{f'?{urlencode(params)}' if params else ''}"
    headers = _headers(api_key)
    data = None
    if json_body is not None:
        data = json.dumps(json_body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = request.Request(url, data=data, headers=headers, method=method)
    try:
        with request.urlopen(req, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except url_error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace") or str(error)
        raise EdgeImpulseError(f"Edge Impulse request failed ({error.code}): {detail}")
    except Exception as error:
        raise EdgeImpulseError(f"Edge Impulse request failed: {error}") from error
    try:
        payload = json.loads(body or "{}")
    except json.JSONDecodeError as error:
        raise EdgeImpulseError(f"Invalid Edge Impulse response: {error}") from error
    if payload.get("success") is False:
        raise EdgeImpulseError(payload.get("error") or "Edge Impulse request failed")
    return payload


def projects(api_key: str) -> list[dict[str, str | int]]:
    payload = _call(api_key, "/api/projects", timeout=30)
    return [
        {"id": int(project["id"]), "name": str(project.get("name") or project["id"])}
        for project in payload.get("projects") or []
        if project.get("id") is not None
    ]


def impulses(api_key: str, project_id: int) -> list[dict[str, str | int]]:
    payload = _call(api_key, f"/api/{project_id}/impulses", timeout=30)
    return [
        {
            "id": int(impulse["id"]),
            "name": str(impulse.get("name") or f"Impulse {impulse['id']}"),
        }
        for impulse in payload.get("impulses") or []
        if impulse.get("id") is not None
    ]


def deployment_targets(api_key: str, project_id: int) -> list[dict[str, str | bool]]:
    """Return the `.eim` runner targets, flagged for this host's architecture."""
    payload = _call(api_key, f"/api/{project_id}/deployment/targets", timeout=30)
    targets = []
    for target in payload.get("targets") or []:
        deployment_format = str(target.get("format") or "")
        if not deployment_format.startswith("runner"):
            continue
        haystack = " ".join(
            str(target.get(key) or "")
            for key in ("format", "name", "description", "uiSection")
        )
        targets.append(
            {
                "format": deployment_format,
                "name": str(target.get("name") or deployment_format),
                "description": str(target.get("description") or ""),
                "compatible": is_compatible(haystack),
            }
        )
    targets.sort(key=lambda target: (not target["compatible"], target["name"]))
    return targets


def _build_deployment(
    api_key: str,
    project_id: int,
    deployment_type: str,
    impulse_id: int | None,
    model_type: str,
    engine: str,
) -> int | None:
    params: dict[str, str | int] = {"type": deployment_type}
    if impulse_id is not None:
        params["impulseId"] = impulse_id
    payload = _call(
        api_key,
        f"/api/{project_id}/jobs/build-ondevice-model",
        params=params,
        json_body={"engine": engine, "modelType": model_type},
        method="POST",
    )
    job_id = payload.get("id")
    if job_id is None:
        raise EdgeImpulseError("Deployment job did not return an id")
    _wait_for_job(api_key, project_id, int(job_id))
    version = payload.get("deploymentVersion")
    return int(version) if version is not None else None


def _wait_for_job(
    api_key: str,
    project_id: int,
    job_id: int,
    timeout: int = 900,
    poll_interval: float = 2.0,
) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        job = (
            _call(api_key, f"/api/{project_id}/jobs/{job_id}/status", timeout=30).get(
                "job"
            )
            or {}
        )
        if job.get("finished"):
            if job.get("finishedSuccessful"):
                return
            raise EdgeImpulseError("Edge Impulse deployment job failed")
        time.sleep(poll_interval)
    raise EdgeImpulseError("Edge Impulse deployment job timed out")


def _deployment_version(
    api_key: str,
    project_id: int,
    deployment_type: str,
    impulse_id: int | None,
    model_type: str,
    engine: str,
) -> int:
    params: dict[str, str | int] = {
        "type": deployment_type,
        "engine": engine,
        "modelType": model_type,
    }
    if impulse_id is not None:
        params["impulseId"] = impulse_id
    payload = _call(api_key, f"/api/{project_id}/deployment", params=params, timeout=30)
    if not payload.get("hasDeployment") or payload.get("version") is None:
        raise EdgeImpulseError("No deployment found matching the requested target")
    return int(payload["version"])


def _download(api_key: str, project_id: int, version: int) -> tuple[str, bytes]:
    url = f"{STUDIO_BASE_URL}/api/{project_id}/deployment/history/{version}/download"
    req = request.Request(url, headers=_headers(api_key))
    try:
        with request.urlopen(req, timeout=600) as response:
            return _filename(
                response.headers.get("content-disposition")
            ), response.read()
    except url_error.HTTPError as error:
        detail = error.read().decode("utf-8", "replace") or str(error)
        raise EdgeImpulseError(
            f"Failed to download deployment ({error.code}): {detail}"
        )
    except Exception as error:
        raise EdgeImpulseError(f"Failed to download deployment: {error}") from error


def _filename(content_disposition: str | None) -> str:
    if not content_disposition:
        return "edge-impulse-model.eim"
    for part in content_disposition.split(";"):
        part = part.strip()
        if part.lower().startswith("filename*="):
            value = part.split("=", 1)[1].strip('"')
            return unquote(value.split("''", 1)[-1])
    for part in content_disposition.split(";"):
        part = part.strip()
        if part.lower().startswith("filename="):
            return part.split("=", 1)[1].strip('"')
    return "edge-impulse-model.eim"


def fetch_model(
    api_key: str,
    project_id: int,
    deployment_type: str,
    models_dir: Path,
    impulse_id: int | None = None,
    model_type: str = "float32",
    engine: str = "tflite",
) -> str:
    """Build the requested deployment and store it as an executable `.eim` file."""
    if model_type not in MODEL_TYPES:
        raise EdgeImpulseError(f"Invalid model type: {model_type}")
    if engine not in ENGINES:
        raise EdgeImpulseError(f"Invalid engine: {engine}")
    version = _build_deployment(
        api_key, project_id, deployment_type, impulse_id, model_type, engine
    )
    if version is None:
        version = _deployment_version(
            api_key, project_id, deployment_type, impulse_id, model_type, engine
        )
    name, data = _download(api_key, project_id, version)
    if not name.endswith(".eim"):
        name = f"{Path(name).stem}.eim"
    models_dir.mkdir(parents=True, exist_ok=True)
    target = models_dir / name
    target.write_bytes(data)
    target.chmod(target.stat().st_mode | 0o111)
    return target.name


class DownloadManager:
    """Runs `.eim` downloads in background threads and exposes their progress."""

    def __init__(self, models_dir: Path) -> None:
        self.models_dir = models_dir
        self._lock = threading.Lock()
        self._jobs: dict[str, dict[str, str | None]] = {}

    def start(self, api_key: str, **options) -> dict[str, str | None]:
        job_id = uuid.uuid4().hex
        with self._lock:
            self._jobs[job_id] = {
                "id": job_id,
                "status": "running",
                "model": None,
                "error": None,
            }
        threading.Thread(
            target=self._run, args=(job_id, api_key, options), daemon=True
        ).start()
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, str | None]:
        with self._lock:
            job = self._jobs.get(job_id)
            if job is None:
                raise KeyError(job_id)
            return dict(job)

    def _run(self, job_id: str, api_key: str, options: dict) -> None:
        try:
            model = fetch_model(api_key, models_dir=self.models_dir, **options)
            update = {"status": "done", "model": model, "error": None}
        except Exception as error:  # noqa: BLE001 - surfaced to the download job
            update = {"status": "error", "model": None, "error": str(error)}
        with self._lock:
            self._jobs[job_id].update(update)
