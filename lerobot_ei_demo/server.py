import asyncio
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from lerobot_ei_demo import edge_impulse
from lerobot_ei_demo.camera import CameraStreamRegistry, camera_index, mjpeg_stream
from lerobot_ei_demo.camera_registry import CameraRegistry
from lerobot_ei_demo.config import AppConfig
from lerobot_ei_demo.hardware import LeRobotController
from lerobot_ei_demo.session import RobotSession, calibration_status, discover_ports
from lerobot_ei_demo.telemetry import TelemetryHub
from lerobot_ei_demo.vision import InferenceService, ModelCatalog

PACKAGE_ROOT = Path(__file__).parent
FRONTEND_ROOT = PACKAGE_ROOT / "frontend"
FRONTEND_DIST = FRONTEND_ROOT / "dist"
app = FastAPI(title="LeRobot + Edge Impulse Demo")
session = RobotSession()
model_catalog = ModelCatalog()
inference = InferenceService(model_catalog)
downloads = edge_impulse.DownloadManager(model_catalog.root)
telemetry = TelemetryHub()
controller = LeRobotController(telemetry.publish)
camera_registry = CameraRegistry()
camera_streams = CameraStreamRegistry()
app_config = AppConfig()
if FRONTEND_DIST.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIST / "assets"), name="assets")


class SessionSelection(BaseModel):
    leader_port: str | None = None
    follower_port: str | None = None
    camera_id: str | None = None


class InferenceAssignment(BaseModel):
    camera_id: str
    model_id: str | None = None
    enabled: bool = False
    confidence: float = 0.5


class EdgeImpulseCredentials(BaseModel):
    api_key: str = Field(min_length=1)
    project_id: int | None = None


class EdgeImpulseConfigRequest(BaseModel):
    api_key: str = Field(min_length=1)
    project_id: int | None = None


class ModelDownload(BaseModel):
    api_key: str = Field(min_length=1)
    project_id: int
    deployment_type: str = Field(min_length=1)
    impulse_id: int | None = None
    model_type: str = "float32"
    engine: str = "tflite"


class CameraRegistration(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    index: int = Field(ge=0, le=31)


class CameraConfiguration(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    index: int = Field(ge=0, le=31)
    selected: bool = False


@app.get("/api/health")
def health() -> dict[str, str]:
    return {
        "status": "ok",
        "robot": "SO-101",
        "mode": session.snapshot()["operation"] or "idle",
    }


@app.get("/api/robots")
def robots() -> list[dict[str, str]]:
    return [{"id": "SO-101", "name": "SO-101 leader/follower"}]


@app.get("/api/ports")
def ports() -> list[str]:
    return discover_ports()


@app.get("/api/cameras")
def cameras() -> list[dict[str, str | bool]]:
    return camera_registry.all()


@app.post("/api/cameras")
def add_camera(camera: CameraRegistration) -> dict[str, str | bool]:
    return camera_registry.register(camera.name.strip(), camera.index)


@app.put("/api/cameras")
def configure_cameras(
    cameras: list[CameraConfiguration],
) -> list[dict[str, str | bool]]:
    try:
        configured = camera_registry.configure(
            [camera.model_dump() for camera in cameras]
        )
        selected_ids = {camera["id"] for camera in configured if camera["selected"]}
        camera_streams.close(previews_only=True)
        camera_streams.close(selected_ids=selected_ids)
        return configured
    except ValueError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error


@app.delete("/api/cameras/{camera_id}")
def remove_camera(camera_id: str) -> dict[str, bool]:
    if not camera_registry.remove(camera_id):
        raise HTTPException(
            status_code=404, detail=f"Manual camera not found: {camera_id}"
        )
    return {"removed": True}


@app.get("/api/cameras/{camera_id}/stream")
def camera_stream(camera_id: str, preview: bool = False) -> StreamingResponse:
    try:
        camera_index(camera_id)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error)) from error
    return StreamingResponse(
        mjpeg_stream(camera_id, camera_streams, preview=preview, inference=inference),
        media_type="multipart/x-mixed-replace; boundary=frame",
    )


@app.get("/api/session")
def get_session() -> dict[str, str | None]:
    return session.snapshot()


@app.get("/api/calibration/status")
def get_calibration_status() -> dict[str, bool]:
    return calibration_status()


@app.post("/api/session/select")
def select_session(selection: SessionSelection) -> dict[str, str | None]:
    return session.select(**selection.model_dump())


@app.post("/api/teleoperation/start")
def start_teleoperation() -> dict[str, str | None]:
    try:
        state = session.start("teleoperation")
        if (
            state["leader_port"]
            and state["follower_port"]
            and Path(state["leader_port"]).exists()
            and Path(state["follower_port"]).exists()
        ):
            try:
                controller.start(state["leader_port"], state["follower_port"])
            except Exception:
                session.stop()
                raise
        return state
    except RuntimeError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except Exception as error:
        raise HTTPException(
            status_code=503, detail=f"Unable to start LeRobot: {error}"
        ) from error


@app.post("/api/teleoperation/stop")
def stop_teleoperation() -> dict[str, str | None]:
    if controller.active:
        controller.stop()
    return session.stop()


@app.websocket("/ws/joint-data")
async def joint_data(websocket: WebSocket) -> None:
    await websocket.accept()
    try:
        while True:
            sample = telemetry.latest()
            if sample is not None:
                await websocket.send_json(sample)
            await asyncio.sleep(0.05)
    except (WebSocketDisconnect, RuntimeError):
        return


@app.get("/api/models")
def models() -> list[dict[str, str | bool]]:
    return model_catalog.list()


@app.get("/api/edge-impulse/architecture")
def architecture() -> dict[str, str]:
    return edge_impulse.host_architecture()


@app.get("/api/edge-impulse/config")
def edge_impulse_config() -> dict[str, str | int | None]:
    return app_config.get_edge_impulse()


@app.put("/api/edge-impulse/config")
def save_edge_impulse_config(
    config: EdgeImpulseConfigRequest,
) -> dict[str, bool]:
    app_config.save_edge_impulse(config.api_key, config.project_id)
    return {"saved": True}


@app.post("/api/edge-impulse/projects")
def edge_impulse_projects(
    credentials: EdgeImpulseCredentials,
) -> list[dict[str, str | int]]:
    try:
        return edge_impulse.projects(credentials.api_key)
    except edge_impulse.EdgeImpulseError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/edge-impulse/targets")
def edge_impulse_targets(
    credentials: EdgeImpulseCredentials,
) -> dict[str, object]:
    if credentials.project_id is None:
        raise HTTPException(status_code=422, detail="project_id is required")
    try:
        return {
            "architecture": edge_impulse.host_architecture(),
            "targets": edge_impulse.deployment_targets(
                credentials.api_key, credentials.project_id
            ),
            "impulses": edge_impulse.impulses(
                credentials.api_key, credentials.project_id
            ),
        }
    except edge_impulse.EdgeImpulseError as error:
        raise HTTPException(status_code=502, detail=str(error)) from error


@app.post("/api/edge-impulse/download")
def edge_impulse_download(payload: ModelDownload) -> dict[str, str | None]:
    return downloads.start(
        payload.api_key,
        project_id=payload.project_id,
        deployment_type=payload.deployment_type,
        impulse_id=payload.impulse_id,
        model_type=payload.model_type,
        engine=payload.engine,
    )


@app.get("/api/edge-impulse/download/{job_id}")
def edge_impulse_download_status(job_id: str) -> dict[str, str | None]:
    try:
        return downloads.status(job_id)
    except KeyError as error:
        raise HTTPException(status_code=404, detail="Download job not found") from error


@app.get("/api/inference/status")
def inference_status() -> dict[str, object]:
    return inference.status()


@app.post("/api/inference/assign")
def assign_inference(assignment: InferenceAssignment) -> dict[str, object]:
    if not 0 <= assignment.confidence <= 1:
        raise HTTPException(
            status_code=422, detail="confidence must be between 0 and 1"
        )
    try:
        return inference.assign(
            assignment.camera_id,
            assignment.model_id,
            assignment.enabled,
            assignment.confidence,
        )
    except FileNotFoundError as error:
        raise HTTPException(status_code=404, detail=str(error)) from error
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error


@app.post("/api/inference/stop")
def stop_inference(camera_id: str | None = None) -> dict[str, object]:
    return inference.clear(camera_id)


@app.get("/")
def index() -> FileResponse:
    bundle_index = FRONTEND_DIST / "index.html"
    return FileResponse(
        bundle_index if bundle_index.exists() else FRONTEND_ROOT / "index.html"
    )


def main() -> None:
    import argparse

    import uvicorn

    parser = argparse.ArgumentParser(
        description="Run the LeRobot and Edge Impulse demo"
    )
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8000, type=int)
    args = parser.parse_args()
    uvicorn.run("lerobot_ei_demo.server:app", host=args.host, port=args.port)
