---
name: lerobot-ei-demo-development
description: "Develop, debug, test, or extend the LeRobot + Edge Impulse SO-101 booth app, including VENTUNO Q deployment, LeRobot teleoperation, camera setup, URDF visualization, joint telemetry, React/Vite UI, FastAPI APIs, and Edge Impulse integration."
---

# LeRobot + Edge Impulse Demo Development

Use this skill when changing the SO-101 booth application in this repository.

## Project shape

- `lerobot_ei_demo/server.py`: FastAPI routes, app lifecycle, WebSocket endpoint, and production frontend serving.
- `lerobot_ei_demo/hardware.py`: lazy LeRobot SO-101 controller and 60 Hz leader-to-follower loop.
- `lerobot_ei_demo/session.py`: thread-safe setup state and USB serial discovery.
- `lerobot_ei_demo/telemetry.py`: bounded joint sample history and `.pos` key normalization.
- `lerobot_ei_demo/camera.py`: OpenCV camera index parsing and MJPEG streaming.
- `lerobot_ei_demo/camera_registry.py`: persistent camera names and saved selections.
- `lerobot_ei_demo/vision.py`: local `.eim` model catalog and inference state boundary.
- `lerobot_ei_demo/frontend/src/`: React/Vite UI, live URDF viewer, cameras, and encoder timeline.
- `lerobot_ei_demo/frontend/dist/`: generated production frontend bundle.
- `tests/`: Python API and pure behavior tests.

## Local commands

```bash
uv sync --extra hardware --extra dev --native-tls
npm --prefix lerobot_ei_demo/frontend install
npm --prefix lerobot_ei_demo/frontend run dev
npm --prefix lerobot_ei_demo/frontend run build
uv run --no-sync ruff check lerobot_ei_demo tests
uv run --no-sync ruff format --check lerobot_ei_demo tests
uv run --no-sync pytest -q
uv run --no-sync lerobot-ei-demo --port 8000
```

Port 8000 is the normal default. Use another port if occupied. Do not use GitKraken tools for repository work.

## Hardware rules

- Target hardware is one SO-101 leader and one SO-101 follower.
- LeRobot is pinned to v0.6.0 through the `hardware` extra.
- Use the persisted port mapping when available under `~/.cache/huggingface/lerobot/ports/`.
- Use `connect(calibrate=False)` for normal startup. Do not invoke fresh calibration blindly: LeRobot calibration is interactive, disables torque, asks the operator to move the arm, and writes calibration files.
- Before a live motion test, state that it can move the follower. After any live test, stop and disconnect the arms.
- Never place inference, camera capture, or network I/O inside the motor-control timing path.
- Handle serial failures by stopping the follower and reporting an actionable state; do not leave the session marked active after a worker crash.

## Telemetry contract

LeRobot follower observations use keys such as `shoulder_pan.pos`. Always pass observations through `TelemetryHub.publish`, which normalizes them to these six names:

```text
shoulder_pan
shoulder_lift
elbow_flex
wrist_flex
wrist_roll
gripper
```

Samples contain `type: joint_update`, a monotonic `timestamp`, and a `joints` object. The same stream feeds the URDF and chart. Keep the history bounded. Calibrated values are degrees; raw Feetech register values must be introduced as a separate explicit field, not silently substituted.

The URDF uses different joint names and expects radians:

```text
shoulder_pan -> Rotation
shoulder_lift -> Pitch
elbow_flex -> Elbow
wrist_flex -> Wrist_Pitch
wrist_roll -> Wrist_Roll
gripper -> Jaw
```

## URDF and frontend rules

- Use the real SO-101 URDF, not a hand-built illustrative chain.
- The viewer uses `urdf-loader` and LeLab's `so101_new_calib.urdf` plus binary meshes from the LeLab `frontend/dist/so-101-urdf` tree.
- Register the custom element with `customElements.define("urdf-viewer", ...)`.
- Assign the four-argument mesh callback before setting the `urdf` attribute.
- Keep the VENTUNO Q visual language light and friendly: pale surfaces, rounded corners, coral/red action accents, and navy encoder telemetry card.
- Keep camera setup separate from saved live camera views. Saved camera names and selections persist locally.
- Frontend production changes require `npm --prefix lerobot_ei_demo/frontend run build` before testing the bundled server.

## Edge Impulse boundary

- Models are discovered from `models/*.eim` or `EI_MODELS_DIR`.
- Use the official `edge_impulse_linux.runner.ImpulseRunner` for compatible Linux EIM image models.
- Initialize the runner, inspect model metadata, and always stop it in `finally`.
- Run inference in a worker with a bounded frame queue.
- Detection results must be normalized to camera-relative coordinates and streamed independently from robot telemetry.
- A model or camera failure must degrade to robot-only operation.

## Change workflow

1. Read the owning module and nearby tests before editing.
2. State one local hypothesis and one cheap check.
3. Make the smallest focused edit.
4. Immediately run the narrowest relevant test or build.
5. For UI changes, run the Vite build and use browser verification when available.
6. For hardware changes, start with import/configuration checks and avoid motion until the exact command and ports are understood.
7. Finish with `ruff`, `pytest`, and frontend build checks when the touched slice spans those areas.

## Safety checklist

Before declaring a live booth change ready:

- Verify stop behavior.
- Verify serial disconnect behavior.
- Verify the app can run with cameras and inference disabled.
- Verify no unbounded queue or history was introduced.
- Verify the production bundle is served by the Python console command.
