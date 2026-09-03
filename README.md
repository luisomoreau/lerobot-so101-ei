# LeRobot + Edge Impulse Demo

A local-first booth application for an SO-101 leader/follower arm pair running on an Arduino VENTUNO Q or a standard Linux computer.

The app combines:

- SO-101 leader-to-follower teleoperation through LeRobot
- Guided setup for serial ports and saved cameras
- Live camera previews with persistent names and selections
- A real SO-101 URDF viewer using LeLab's model assets
- Live joint telemetry and a six-joint encoder timeline
- An optional Edge Impulse model lifecycle for future camera inference

## Quick Start

Install the hardware-enabled tool from a Git repository:

```bash
uv tool install 'lerobot-ei-demo[hardware] @ git+https://github.com/<org>/<repo>.git'
lerobot-ei-demo
```

For a checkout during development:

```bash
uv sync --extra hardware --extra dev --native-tls
uv run lerobot-ei-demo --port 8000
```

Open the printed local URL. If port 8000 is already in use, choose another one:

```bash
uv run lerobot-ei-demo --port 8001
```

The `--native-tls` option may be needed on managed machines whose Python certificate store does not trust package indexes.

## Hardware Setup

The application currently targets one SO-101 leader and one SO-101 follower.

1. Connect both arms by USB.
2. Confirm the ports with LeRobot:

   ```bash
   uv run lerobot-find-port
   ```

3. Ensure calibration files exist for both roles. The default LeRobot locations are under:

   ```text
   ~/.cache/huggingface/lerobot/calibration/
   ```

4. Start the app and verify the saved leader and follower ports in the setup controls.
5. Start teleoperation only after the follower workspace is clear and the operator has access to the physical emergency stop.

The app uses `connect(calibrate=False)` for normal startup so it never silently opens LeRobot's interactive calibration prompts. Fresh calibration needs a dedicated guided flow before it should be enabled for booth use.

## Cameras

The setup page detects OpenCV camera indices and allows additional indices to be entered manually.

1. Select **Set up cameras**.
2. Name each camera using a booth-friendly name such as `Overhead` or `Wrist`.
3. Select the cameras to use.
4. Save the configuration.

Only saved cameras appear in the main live view. Configuration is stored at:

```text
~/.cache/huggingface/lerobot-ei-demo/cameras.json
```

Each saved camera has an independent stream at `/api/cameras/{camera_id}/stream`.

## Development

Backend files live in `lerobot_ei_demo/`. The frontend is a React/Vite application in `lerobot_ei_demo/frontend/`.

Run frontend development mode:

```bash
npm --prefix lerobot_ei_demo/frontend install
npm --prefix lerobot_ei_demo/frontend run dev
```

The Vite development server proxies `/api` to `127.0.0.1:8000`. Build the production frontend before testing the bundled Python application:

```bash
npm --prefix lerobot_ei_demo/frontend run build
```

The Python server serves `frontend/dist/` when it exists and falls back to the source entrypoint otherwise.

## Testing

```bash
uv run --no-sync ruff check lerobot_ei_demo tests
uv run --no-sync ruff format --check lerobot_ei_demo tests
uv run --no-sync pytest -q
npm --prefix lerobot_ei_demo/frontend run build
```

Hardware tests should be performed deliberately with the arms secured. Unit tests do not move hardware.

## Architecture

```text
React/Vite
  setup, saved camera views, URDF viewer, encoder timeline
          | HTTP + WebSocket + MJPEG
          v
FastAPI
  RobotSession   LeRobotController   TelemetryHub   CameraRegistry
          |             |                  |
          +--> SO-101 serial arms    joint-data WebSocket
          +--> OpenCV cameras         Edge Impulse integration boundary
```

The telemetry stream publishes normalized joint names:

```json
{
  "type": "joint_update",
  "timestamp": 123.45,
  "joints": {
    "shoulder_pan": 0.0,
    "shoulder_lift": -20.0,
    "elbow_flex": 45.0,
    "wrist_flex": 10.0,
    "wrist_roll": 0.0,
    "gripper": 20.0
  }
}
```

LeRobot observations arrive as keys such as `shoulder_pan.pos`; `TelemetryHub` removes the `.pos` suffix before publishing. The current values are calibrated joint positions in degrees, not raw Feetech register counts.

The URDF viewer uses LeLab's `so101_new_calib.urdf` and binary mesh assets from its distribution tree. If the booth must run offline, mirror those assets into the package instead of relying on the CDN URL in the frontend.

## Current Boundaries

- SO-101 is the only robot type implemented.
- Calibration is not yet exposed as a guided web workflow.
- Edge Impulse model discovery exists, but the asynchronous `.eim` inference worker and detection overlays are still to be completed.
- Teleoperation and telemetry are implemented; disconnect recovery and operator-facing fault states need further hardening.
- The encoder timeline currently shows calibrated positions. Raw encoder register telemetry should be added as a separate field if required.

## Safety

This application can move physical hardware. Before pressing **Start teleoperation**:

- Clear people and objects from the follower workspace.
- Use conservative operating limits.
- Keep a physical emergency stop available.
- Stop the application before changing USB connections.
- Never run an unreviewed control-loop change directly at a public booth.

## Related Work

- [LeLab](https://github.com/huggingface/leLab/): reference web interface and SO-101 URDF assets
- [LeRobot](https://github.com/huggingface/lerobot): robot control framework
- [Edge Impulse Linux Python SDK](https://docs.edgeimpulse.com/tools/libraries/sdks/inference/linux/python): image inference runtime
- [Arduino VENTUNO Q](https://www.arduino.cc/product-ventuno-q): target edge AI platform
