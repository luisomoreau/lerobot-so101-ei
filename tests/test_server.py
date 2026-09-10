from pathlib import Path
from threading import Lock

import numpy as np
from fastapi.testclient import TestClient

from lerobot_ei_demo import server
from lerobot_ei_demo.edge_impulse import host_architecture, is_compatible
from lerobot_ei_demo.server import app
from lerobot_ei_demo.telemetry import TelemetryHub
from lerobot_ei_demo.vision import (
    RunnerState,
    _map_detection,
    _mask_unused_regions,
    _result_items,
)

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_calibration_status_has_both_roles() -> None:
    response = client.get("/api/calibration/status")

    assert response.status_code == 200
    assert set(response.json()) == {"leader", "follower"}


def test_calibration_session_is_idle_without_hardware() -> None:
    response = client.get("/api/calibration/session")

    assert response.status_code == 200
    assert response.json()["status"] == "idle"


def test_import_calibration_writes_official_role_path(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    response = client.post(
        "/api/calibration/import",
        json={"role": "leader", "contents": '{"motors": {"shoulder_pan": 1}}'},
    )

    target = (
        tmp_path
        / ".cache/huggingface/lerobot/calibration/teleoperators/so_leader/SO101.json"
    )
    assert response.status_code == 200
    assert target.exists()
    assert target.read_text(encoding="utf-8").startswith('{\n  "motors"')
    assert target.stat().st_mode & 0o777 == 0o600

    download = client.get("/api/calibration/download/leader")
    assert download.status_code == 200
    assert download.json()["motors"]["shoulder_pan"] == 1


def test_import_calibration_rejects_invalid_json(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    response = client.post(
        "/api/calibration/import",
        json={"role": "follower", "contents": "not-json"},
    )

    assert response.status_code == 422


def test_telemetry_normalizes_lerobot_position_keys() -> None:
    sample = TelemetryHub().publish({"shoulder_pan.pos": -12.5, "gripper.pos": 0.6})

    assert sample["joints"] == {"shoulder_pan": -12.5, "gripper": 0.6}


def test_index() -> None:
    response = client.get("/")

    assert response.status_code == 200
    assert '<div id="root"></div>' in response.text
    assert "/assets/" in response.text


def test_frontend_asset_is_served() -> None:
    index = client.get("/")
    asset_path = next(
        line.split('src="')[1].split('"')[0]
        for line in index.text.splitlines()
        if 'src="/assets/' in line
    )

    response = client.get(asset_path)

    assert response.status_code == 200


def test_session_setup_and_operation_lock(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))

    response = client.post(
        "/api/session/select",
        json={"leader_port": "/dev/cu.leader", "follower_port": "/dev/cu.follower"},
    )

    assert response.status_code == 200
    assert response.json()["leader_port"] == "/dev/cu.leader"

    response = client.post("/api/teleoperation/start")
    assert response.status_code == 200
    assert response.json()["operation"] == "teleoperation"

    response = client.post("/api/teleoperation/start")
    assert response.status_code == 409

    response = client.post("/api/teleoperation/stop")
    assert response.status_code == 200
    assert response.json()["operation"] == "idle"


def test_inference_model_lifecycle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(server.model_catalog, "root", tmp_path)
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json() == []

    response = client.post(
        "/api/inference/assign",
        json={"camera_id": "opencv:0", "model_id": "missing.eim", "enabled": True},
    )
    assert response.status_code == 404

    response = client.post("/api/inference/stop")
    assert response.status_code == 200
    assert response.json()["cameras"] == []


def test_upload_now_requires_recent_frame(tmp_path, monkeypatch) -> None:
    model = tmp_path / f"model-{host_architecture()['architecture']}.eim"
    model.write_bytes(b"stub")
    monkeypatch.setattr(server.model_catalog, "root", tmp_path)
    client.post(
        "/api/inference/assign",
        json={"camera_id": "opencv:0", "model_id": model.name, "enabled": False},
    )

    response = client.post("/api/inference/upload", params={"camera_id": "opencv:0"})

    assert response.status_code == 400
    client.post("/api/inference/stop")


def test_upload_now_sets_bounding_boxes_for_object_detection_but_not_fomo(
    monkeypatch,
) -> None:
    from lerobot_ei_demo import vision as vision_module

    upload_calls = []

    def fake_upload_files(
        api_key,
        category,
        files,
        label=None,
        no_label=False,
        metadata=None,
        bounding_boxes=None,
        timeout=30,
    ):
        upload_calls.append(
            {
                "no_label": no_label,
                "metadata": metadata,
                "bounding_boxes": bounding_boxes,
            }
        )
        return "ok"

    monkeypatch.setattr(vision_module.ingestion, "upload_files", fake_upload_files)
    monkeypatch.setattr(
        server.app_config,
        "get_edge_impulse",
        lambda: {"api_key": "test-key", "project_id": 123},
    )

    frame = np.zeros((10, 10, 3), dtype="uint8")
    detections = [
        {"label": "cube", "confidence": 0.9, "x": 1, "y": 1, "width": 4, "height": 4}
    ]

    with server.inference._lock:
        server.inference._assignments["opencv:0"] = vision_module.CameraInference(
            camera_id="opencv:0", model_id="model.eim", enabled=True
        )
        server.inference._last_frames["opencv:0"] = frame
        server.inference._last_detections["opencv:0"] = detections
        server.inference._last_model["opencv:0"] = {
            "model_id": "model.eim",
            "is_fomo": False,
            "centroid_only": False,
        }

    server.inference.upload_now("opencv:0")

    assert len(upload_calls) == 1
    assert upload_calls[0]["no_label"] is True
    assert upload_calls[0]["metadata"] == {"source": "SO101-opencv-0-camera"}
    assert upload_calls[0]["bounding_boxes"] == [
        {"label": "cube", "x": 1, "y": 1, "width": 4, "height": 4}
    ]

    with server.inference._lock:
        server.inference._last_model["opencv:0"]["is_fomo"] = True
        server.inference._last_model["opencv:0"]["centroid_only"] = True

    server.inference.upload_now("opencv:0")

    assert len(upload_calls) == 2
    assert upload_calls[1]["bounding_boxes"] is None

    server.inference.clear()


def test_upload_now_works_without_a_model_assigned(monkeypatch) -> None:
    from lerobot_ei_demo import vision as vision_module

    calls = []

    def fake_upload_files(
        api_key,
        category,
        files,
        label=None,
        no_label=False,
        metadata=None,
        bounding_boxes=None,
        timeout=30,
    ):
        calls.append({"label": label, "no_label": no_label})
        return "ok"

    monkeypatch.setattr(vision_module.ingestion, "upload_files", fake_upload_files)
    monkeypatch.setattr(
        server.app_config,
        "get_edge_impulse",
        lambda: {"api_key": "test-key", "project_id": None},
    )

    frame = np.zeros((10, 10, 3), dtype="uint8")
    with server.inference._lock:
        server.inference._last_frames["opencv:0"] = frame

    result = server.inference.upload_now("opencv:0")

    assert len(calls) == 1
    assert calls[0]["no_label"] is True
    cameras = {entry["camera_id"]: entry for entry in result["cameras"]}
    assert cameras["opencv:0"]["last_upload_status"] == "ok"

    server.inference.clear()


def test_inference_assignment_is_per_camera(tmp_path, monkeypatch) -> None:
    model = tmp_path / f"model-{host_architecture()['architecture']}.eim"
    model.write_bytes(b"stub")
    monkeypatch.setattr(server.model_catalog, "root", tmp_path)

    for camera_id in ("opencv:0", "opencv:1"):
        response = client.post(
            "/api/inference/assign",
            json={"camera_id": camera_id, "model_id": model.name, "enabled": False},
        )
        assert response.status_code == 200

    cameras = {entry["camera_id"]: entry for entry in response.json()["cameras"]}
    assert set(cameras) == {"opencv:0", "opencv:1"}
    assert cameras["opencv:0"]["model_id"] == model.name

    client.post("/api/inference/stop")


def test_incompatible_models_cannot_be_enabled(tmp_path, monkeypatch) -> None:
    incompatible = "linux" if host_architecture()["system"] == "darwin" else "macos"
    model = tmp_path / f"model-{incompatible}-x86_64.eim"
    model.write_bytes(b"stub")
    monkeypatch.setattr(server.model_catalog, "root", tmp_path)

    listed = client.get("/api/models").json()
    assert listed[0]["compatible"] is False

    response = client.post(
        "/api/inference/assign",
        json={"camera_id": "opencv:0", "model_id": model.name, "enabled": True},
    )
    assert response.status_code == 409

    client.post("/api/inference/stop")


def test_host_architecture_is_reported() -> None:
    response = client.get("/api/edge-impulse/architecture")

    assert response.status_code == 200
    assert response.json()["label"] == host_architecture()["label"]


def test_edge_impulse_config_is_stored_locally(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(server.app_config, "path", tmp_path / "config.json")

    response = client.put(
        "/api/edge-impulse/config",
        json={"api_key": "ei_test_key", "project_id": 123},
    )

    assert response.status_code == 200
    assert client.get("/api/edge-impulse/config").json() == {
        "api_key": "ei_test_key",
        "project_id": 123,
    }
    assert (tmp_path / "config.json").stat().st_mode & 0o777 == 0o600


def test_compatibility_matches_the_running_host() -> None:
    host = host_architecture()

    assert is_compatible(f"{host['system']}-{host['architecture']}") is True


def test_inference_results_map_boxes_and_centroids_to_camera_frames() -> None:
    runner = RunnerState(
        runner=None,
        width=100,
        height=100,
        resize_mode="squash",
        grayscale=False,
        centroid_only=False,
        lock=Lock(),
    )

    boxes = _result_items(
        {
            "result": {
                "bounding_boxes": [
                    {
                        "label": "cup",
                        "value": 0.9,
                        "x": 10,
                        "y": 20,
                        "width": 50,
                        "height": 30,
                    }
                ]
            }
        }
    )
    mapped_box = _map_detection(boxes[0], (200, 200, 3), runner)
    assert mapped_box == {
        "label": "cup",
        "confidence": 0.9,
        "x": 20,
        "y": 40,
        "width": 100,
        "height": 60,
    }

    centroids = _result_items(
        {
            "result": {
                "centroids": [{"label": "ball", "value": 0.8, "x": 0.5, "y": 0.25}]
            }
        }
    )
    mapped_centroid = _map_detection(centroids[0], (200, 200, 3), runner)
    assert mapped_centroid["label"] == "ball"
    assert (mapped_centroid["x"], mapped_centroid["y"]) == (100, 50)
    assert mapped_centroid["width"] == mapped_centroid["height"] == 0

    fomo_runner = RunnerState(
        runner=None,
        width=100,
        height=100,
        resize_mode="squash",
        grayscale=False,
        centroid_only=True,
        lock=Lock(),
    )
    mapped_fomo = _map_detection(boxes[0], (200, 200, 3), fomo_runner)
    assert (mapped_fomo["x"], mapped_fomo["y"]) == (70, 70)
    assert mapped_fomo["width"] == mapped_fomo["height"] == 0


def test_inference_masks_cropped_regions_for_fit_shortest() -> None:
    runner = RunnerState(
        runner=None,
        width=100,
        height=100,
        resize_mode="fit-shortest",
        grayscale=False,
        centroid_only=False,
        lock=Lock(),
    )
    frame = np.full((100, 200, 3), 255, dtype=np.uint8)

    masked = _mask_unused_regions(frame, runner)

    assert masked[50, 10, 0] < 255
    assert masked[50, 100, 0] == 255


def test_ports_only_include_usb_devices() -> None:
    response = client.get("/api/ports")

    assert response.status_code == 200
    assert all("usb" in port for port in response.json())


def test_cameras_have_stable_identifiers() -> None:
    response = client.get("/api/cameras")

    assert response.status_code == 200
    assert all(camera["id"].startswith("opencv:") for camera in response.json())


def test_invalid_camera_stream_id_is_rejected() -> None:
    response = client.get("/api/cameras/not-a-camera/stream")

    assert response.status_code == 400


def test_manual_camera_registration_is_persistent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(server.camera_registry, "path", tmp_path / "cameras.json")

    response = client.post("/api/cameras", json={"name": "Wrist camera", "index": 6})

    assert response.status_code == 200
    assert response.json() == {
        "id": "opencv:6",
        "name": "Wrist camera",
        "index": "6",
        "manual": True,
        "selected": True,
    }
    assert any(
        camera["name"] == "Wrist camera" for camera in client.get("/api/cameras").json()
    )

    response = client.delete("/api/cameras/opencv:6")
    assert response.status_code == 200


def test_camera_selection_and_names_are_persistent(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(server.camera_registry, "path", tmp_path / "cameras.json")

    response = client.put(
        "/api/cameras",
        json=[
            {"name": "Overhead", "index": 0, "selected": True},
            {"name": "Wrist", "index": 1, "selected": False},
        ],
    )

    assert response.status_code == 200
    assert response.json()[0]["name"] == "Overhead"
    cameras = client.get("/api/cameras").json()
    assert cameras[0]["selected"] is True
    assert cameras[1]["selected"] is False


def test_joint_data_websocket_sends_timestamped_samples(monkeypatch) -> None:
    hub = TelemetryHub()
    hub.publish(
        {
            name: index
            for index, name in enumerate(
                (
                    "shoulder_pan",
                    "shoulder_lift",
                    "elbow_flex",
                    "wrist_flex",
                    "wrist_roll",
                    "gripper",
                )
            )
        }
    )
    monkeypatch.setattr(server, "telemetry", hub)

    with client.websocket_connect("/ws/joint-data") as websocket:
        sample = websocket.receive_json()

    assert sample["type"] == "joint_update"
    assert set(sample["joints"]) == {
        "shoulder_pan",
        "shoulder_lift",
        "elbow_flex",
        "wrist_flex",
        "wrist_roll",
        "gripper",
    }
    assert isinstance(sample["timestamp"], float)
