# TidyBot Sim Server

Simulated TidyBot agent server — runs a MuJoCo-based kitchen environment with a web dashboard, robot SDK, and code execution sandbox.

## Prerequisites

- Python 3.11+
- macOS (MuJoCo rendering requires `mjpython` from the `mujoco` package for GUI mode)

## Setup

```bash
# Clone with submodules
git clone https://github.com/TidyBot-Services/sim.git
cd sim

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Install robosuite and robocasa (editable, pulls their own dependencies)
pip install -e robosuite/
pip install -e robocasa/

# Install agent server dependencies
pip install -r requirements.txt

# Install TidyVerse robot into robosuite
./setup.sh
```

> **Note:** `setup.sh` initializes git submodules and runs `tidyverse/setup.py`, which copies the TidyVerse robot assets (meshes, XML, controllers) into robosuite and patches the registration files. It's safe to run multiple times.

### RoboCasa assets

RoboCasa downloads kitchen fixtures on first use. You can trigger this manually:

```bash
python -m robocasa.scripts.download_kitchen_assets
```

## Running

### Server + GUI (MuJoCo viewer window)

```bash
mjpython -m agent_server.server
```

Then open the dashboard at http://localhost:8080 and click **Server + GUI**.

### Server only (headless)

```bash
python -m agent_server.server
```

Open http://localhost:8080 and click **Server Only**. Camera views on the dashboard still work (rendered offscreen via `mujoco.Renderer`).

### CLI options

```bash
mjpython -m agent_server.server \
    --host 0.0.0.0 \
    --port 8080 \
    --task BananaTestKitchen \
    --robot TidyVerse \
    --layout 1 \
    --style 1
```

## Project Structure

```
sim/
├── agent_server/           # FastAPI server
│   ├── server.py           # Main app, sim lifecycle, ZMQ bridge
│   ├── sim_robot.py        # SimRobot wrapper around robosuite env
│   ├── code_executor.py    # Sandboxed Python code execution
│   ├── lease.py            # Lease-based access control
│   ├── config.py           # Server and control config
│   ├── zmq_bridge.py       # Thread-safe sim access from executor
│   ├── robot_sdk/          # TidyBot-compatible Python SDK
│   │   ├── arm.py          # Arm control (IK, move_to_pose, go_home)
│   │   ├── base.py         # Mobile base control
│   │   ├── gripper.py      # Gripper open/close
│   │   ├── sensors.py      # Camera frames, state queries
│   │   └── yolo.py         # YOLO segmentation (remote server)
│   └── routes/
│       ├── dashboard.py    # Web dashboard (inline HTML)
│       ├── state_routes.py # Camera MJPEG streams, robot state
│       ├── code_routes.py  # Code execution API
│       └── lease_routes.py # Lease management API
├── tidyverse/              # TidyVerse robot definition
│   ├── assets/             # Meshes, XML, Python, controller config
│   └── setup.py            # Installs robot into robosuite
├── robocasa/               # Submodule → upstream robocasa/robocasa
├── robosuite/              # Submodule → upstream ARISE-Initiative/robosuite
├── setup.sh                # One-command setup
└── requirements.txt        # Agent server Python dependencies
```

## API

### Simulation control

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/start` | POST | Start simulation (`{"gui": true/false}`) |
| `/api/stop` | POST | Stop simulation |
| `/api/reset` | POST | Reset scene to initial state |
| `/api/sim_status` | GET | Running status and uptime |

### Robot state and cameras

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/state` | GET | Base pose, EE pose, gripper state |
| `/api/camera/{name}` | GET | Single JPEG frame |
| `/api/camera/{name}/stream` | GET | MJPEG stream (~20fps) |

Camera names: `robot0_agentview_center`, `robot0_eye_in_hand`

### Code execution (requires lease)

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/code/execute` | POST | Submit Python code |
| `/api/code/status` | GET | Live stdout/stderr with offset polling |
| `/api/code/result` | GET | Last execution result |
| `/api/code/stop` | POST | Stop running code |
| `/api/code/history` | GET | Execution history |

### Lease management

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/lease/acquire` | POST | Acquire lease (`{"holder": "name"}`) |
| `/api/lease/release` | POST | Release lease |
| `/api/lease/status` | GET | Current lease info |

## SDK Usage (via code execution)

Acquire a lease, then submit code through the API:

```python
from robot_sdk import arm, base, gripper

# Move arm
arm.go_home()
arm.move_to_pose([0.5, 0.0, 0.3], [0, 0, 0])

# Gripper
gripper.close()
gripper.open()

# Mobile base
base.move_forward(0.3)
base.rotate(1.57)
```

## Updating submodules

To pull upstream changes from robocasa/robosuite:

```bash
cd robocasa && git pull origin main && cd ..
cd robosuite && git pull origin master && cd ..
python tidyverse/setup.py   # re-patch after update
```
