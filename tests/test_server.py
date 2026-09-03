from fastapi.testclient import TestClient

from lerobot_ei_demo import server
from lerobot_ei_demo.server import app
from lerobot_ei_demo.telemetry import TelemetryHub

client = TestClient(app)


def test_health() -> None:
    response = client.get("/api/health")

    assert response.status_code == 200
    assert response.json()["status"] == "ok"


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


def test_session_setup_and_operation_lock() -> None:
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


def test_inference_model_lifecycle() -> None:
    response = client.get("/api/models")
    assert response.status_code == 200
    assert response.json() == []

    response = client.post(
        "/api/inference/start",
        json={"model_id": "missing.eim", "camera_id": "workspace"},
    )
    assert response.status_code == 404

    response = client.post("/api/inference/stop")
    assert response.status_code == 200
    assert response.json()["status"] == "idle"


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
