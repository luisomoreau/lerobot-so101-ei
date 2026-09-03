# LeRobot + Edge Impulse Booth Demo

## Goal

Build a reliable, local-first booth application for an SO-101 leader/follower pair. A participant should be able to select the robot, calibrate it, teleoperate it, see the robot in a URDF view and camera views, and optionally run an Edge Impulse object-detection model over the camera stream.

The application should use LeLab as the starting point for robot lifecycle, calibration, teleoperation, and frontend/backend packaging. Edge Impulse is an optional vision pipeline and must never block robot control.

## MVP experience

1. Start the app with one command.
2. Select `SO-101` and the configured leader/follower serial ports.
3. Select the workspace camera.
4. Run guided calibration for the leader and follower.
5. Start teleoperation.
6. View live joint state, URDF visualization, and camera frames.
7. Select and enable a local Edge Impulse `.eim` object-detection model.
8. See bounding boxes and labels over the selected camera view.
9. Stop teleoperation or inference independently, with a prominent emergency stop path.

The initial demo supports one robot pair, one or two known cameras, and one local model. Recording, training, replay, Hub upload, and multi-robot support are out of scope for the first booth version.

## Architecture

```text
React/Vite browser UI
  Setup, calibration, play, vision controls
       | HTTP + WebSocket
       v
FastAPI application
  Robot session and operation lock
  LeLab calibration and teleoperation adapters
  Camera capture and frame streaming
  Edge Impulse inference worker
       |
       +-- LeRobot / SO-101 serial devices
       +-- USB cameras (browser cameras as optional fallback)
       +-- Edge Impulse .eim model
```

### Backend boundaries

- `RobotSession`: selected robot, ports, lifecycle, connection state, and exclusive operation state.
- `CalibrationService`: guided steps, progress, cancellation, retries, and persisted calibration files.
- `TeleoperationService`: leader-to-follower loop, joint-data WebSocket messages, fault reporting, and stop handling.
- `CameraService`: camera enumeration, deterministic selection, capture, health, and JPEG frame streaming.
- `EdgeImpulseService`: model discovery, load/unload, inference workers, normalized detections, and model metrics.

Inference must run in a worker thread or process. It must consume camera frames without being in the teleoperation control loop. A model error, slow inference cycle, or camera failure must not stop or delay leader-to-follower control.

### Frontend views

- **Setup**: SO-101 selector, leader/follower ports, cameras, connection checks.
- **Calibration**: one guided step at a time with progress, retry, restart, and clear status.
- **Play**: URDF robot view, camera panels, joint state, latency/health indicators, start/stop, and emergency stop.
- **Vision**: model picker, camera assignment, enable/disable, confidence threshold, bounding-box overlay, inference FPS, and model status.

## Implementation milestones

### 0. Repository and packaging baseline

- Create a Python package with a `lelerobot-ei-demo` or equivalent console entry point.
- Pin Python, LeRobot, and hardware-sensitive dependencies.
- Bundle the built frontend into the Python distribution.
- Add development, test, lint, and production run commands.
- Add a local demo profile for known serial ports and cameras.

Done when a clean machine can install and start the application from the documented command.

### 1. LeLab SO-101 baseline

- Integrate or pin the LeLab SO-101 implementation.
- Verify leader/follower port discovery and connection diagnostics.
- Verify guided calibration for both arms.
- Verify teleoperation start, stop, disconnect, and restart behavior.
- Verify the URDF/joint stream and existing camera view.

Done when the complete robot-only workflow works repeatedly with the target hardware.

### 2. Booth-oriented control surface

- Reduce navigation to Setup, Calibrate, and Play.
- Add a single session state and operation lock.
- Add visible connection, calibration, teleoperation, camera, and inference states.
- Add software stop controls and integrate a physical emergency-stop procedure.
- Persist selected ports, cameras, and calibration locations.

Done when a new participant can reach Play without CLI prompts or hidden setup steps.

### 3. Deterministic camera pipeline

- Enumerate cameras on the host and save stable selections.
- Capture frames server-side with a fixed resolution and bounded frame rate.
- Stream frames and camera health to the browser.
- Keep HTTPS/browser-camera support optional for later phone-camera demos.

Done when the displayed frame and the frame used for inference are from the same selected camera.

### 4. Edge Impulse integration

- Add a local models directory and model metadata discovery.
- Load and unload `.eim` models without restarting robot control.
- Run image inference asynchronously.
- Normalize detections to camera-relative coordinates.
- Stream detection results independently from video frames.
- Render labels and bounding boxes in the frontend.
- Show inference latency, FPS, confidence threshold, and errors.

Done when enabling or disabling the model never changes teleoperation behavior and detections remain aligned with the camera image.

### 5. Booth hardening

- Add automatic startup using a known demo profile.
- Handle unplugged serial devices and cameras with recovery instructions.
- Add watchdogs and bounded queues for teleoperation, video, and inference.
- Add a vision-disabled fallback mode.
- Run a several-hour soak test with repeated participant sessions.
- Test with no internet access after installation.
- Package a release artifact and a one-line install document.

Done when the demo can be reset and used repeatedly by non-developers.

## Packaging and installation

The target user experience is:

```bash
uv tool install git+https://github.com/<org>/<repo>.git
lerobot-ei-demo
```

Development install:

```bash
uv tool install --editable .
lerobot-ei-demo --dev
```

The package should include the frontend build and install the pinned LeRobot and Edge Impulse runtime dependencies. The exact LeLab and LeRobot versions must be recorded once the hardware baseline is verified.

## API sketch

- `GET /api/robots`
- `GET /api/ports`
- `GET /api/cameras`
- `POST /api/session/select`
- `POST /api/calibration/start`
- `POST /api/calibration/step`
- `POST /api/calibration/cancel`
- `POST /api/teleoperation/start`
- `POST /api/teleoperation/stop`
- `POST /api/inference/start`
- `POST /api/inference/stop`
- `GET /api/models`
- `WS /ws/joint-data`
- `WS /ws/camera/{camera_id}`
- `WS /ws/detections/{camera_id}`

All mutating endpoints should be idempotent where practical and return explicit state. WebSocket payloads should include timestamps and source identifiers.

## Safety and reliability requirements

- Inference must not run inside the teleoperation loop.
- Stop must be available from every Play state.
- Serial disconnects must stop follower motion and report the cause.
- Camera or model failures must degrade to robot-only teleoperation.
- Default speed and workspace limits must be conservative for public use.
- The booth operator must have a physical emergency-stop procedure.
- No cloud connection should be required during the live demo.

## Validation checklist

- Fresh `uv tool install` succeeds on the target operating system.
- App starts with the documented command and opens the UI.
- SO-101 ports are detected and selectable.
- Both arms calibrate through the UI.
- Teleoperation starts and stops repeatedly.
- URDF and camera views remain responsive during teleoperation.
- Inference can be started, stopped, and restarted independently.
- Bounding boxes align with the correct camera frames.
- Unplugging a camera or serial cable produces a recoverable state.
- The demo remains usable with inference disabled.
- A long-running soak test completes without unbounded memory or queue growth.

## First implementation slice

Create the package scaffold and a thin FastAPI health endpoint, then add the frontend shell and packaging metadata. Do not connect hardware until the package starts cleanly. The next slice should integrate the pinned LeLab SO-101 baseline and replace the health screen with real setup state.
