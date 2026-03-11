# TidyBot Universe Servers

Simulated TidyBot environment — runs MuJoCo physics with protocol bridges that emulate real hardware servers, so the [agent_server](https://github.com/TidyBot-Services/agent_server) connects transparently to either sim or real hardware.

## Architecture

```
sim_server (MuJoCo physics)
  ├── base_server.server.BaseBridge        ← base_tidybot_sim_service
  ├── franka_server.server.FrankaBridge    ← arm_franka_sim_service
  ├── gripper_server.server.GripperBridge  ← gripper_robotiq_sim_service
  ├── camera_server.server.CameraBridge    ← camera_realsense_sim_service
  └── sim_server.bridges.http_api          (sim-only HTTP control)

agent_server (FastAPI :8080)
  ├── backends/franka.py   → from franka_server.client import FrankaClient
  ├── backends/gripper.py  → from gripper_server.client import GripperClient
  ├── backends/cameras.py  → from camera_server.client import CameraClient
  └── backends/base.py     → multiprocessing.managers (port 50000)
```

Each bridge is a separate pip-installable package with the **same package name** as the real hardware service (`franka_server`, `gripper_server`, `base_server`, `camera_server`). The agent_server imports work unchanged for both sim and real.

## Setup

```bash
git clone https://github.com/TidyBot-Services/sim.git tidybot_universe_servers
cd tidybot_universe_servers
conda create -n tidybot_sim python=3.11
conda activate tidybot_sim
./setup.sh
```

`setup.sh` handles everything:
1. Clones robocasa/robosuite
2. Clones and pip-installs the four sim service repos
3. Checks for sibling repos (agent_server, system_logger)
4. Installs Python packages
5. Patches TidyVerse robot assets into robosuite

### Sim service repos (cloned and installed by setup.sh)

| Repo | Package | Protocol | Port(s) |
|------|---------|----------|---------|
| [arm_franka_sim_service](https://github.com/TidyBot-Services/arm_franka_sim_service) | `franka_server` | ZMQ (msgpack) | 5555, 5556, 5557 |
| [gripper_robotiq_sim_service](https://github.com/TidyBot-Services/gripper_robotiq_sim_service) | `gripper_server` | ZMQ (msgpack) | 5570, 5571 |
| [base_tidybot_sim_service](https://github.com/TidyBot-Services/base_tidybot_sim_service) | `base_server` | multiprocessing.managers RPC | 50000 |
| [camera_realsense_sim_service](https://github.com/TidyBot-Services/camera_realsense_sim_service) | `camera_server` | WebSocket (binary JPEG/PNG) | 5580 |

## Running

**Terminal 1 — sim server:**

```bash
conda activate tidybot_sim
mjpython -m sim_server
```

**Terminal 2 — agent server:**

```bash
conda activate tidybot_sim
cd agent_server && python3 server.py
```

The sim server starts MuJoCo and loads the four bridge plugins. The agent_server connects to these ports and exposes the unified REST/WebSocket API on port 8080.

### CLI options

```bash
mjpython -m sim_server \
    --task BananaTestKitchen \
    --robot TidyVerse \
    --layout 1 \
    --style 1 \
    --no-gui                  # headless (no MuJoCo viewer)
    --no-base-bridge          # disable individual bridges
    --no-franka-bridge
    --no-gripper-bridge
    --no-camera-bridge
```

## Project Structure

```
tidybot_universe_servers/
├── sim_server/                    # MuJoCo sim server package
│   ├── __main__.py                #   Entry point (imports from installed packages)
│   ├── server.py                  #   Physics loop + command queue
│   ├── sim_robot.py               #   SimRobot: robosuite env wrapper
│   ├── config.py                  #   Control tuning constants
│   ├── scenes.py                  #   Custom scene registration
│   ├── bridges/
│   │   └── http_api.py            #   Sim-only HTTP control API (port 8081)
│   └── camera_mjpeg_server/       #   Optional MJPEG frame server + YOLO client
├── tidybot_assets/                # TidyVerse robot definition
│   ├── assets/                    #   MuJoCo meshes, XML, controllers
│   └── setup.py                   #   Patches assets into robosuite
├── setup.sh
└── requirements.txt
```

### External repos (cloned by setup.sh)

| Repo | Description |
|------|-------------|
| [robosuite](https://github.com/ARISE-Initiative/robosuite) | MuJoCo robot simulation framework |
| [robocasa](https://github.com/robocasa/robocasa) | Kitchen environments for robosuite |
| [agent_server](https://github.com/TidyBot-Services/agent_server) | FastAPI server with SDK, dashboard, code execution |
| [system_logger](https://github.com/TidyBot-Services/system_logger) | Logging utilities |

## Manual Setup (without setup.sh)

If you prefer to set up manually or need to add the sim service packages to an existing environment:

```bash
# Clone the four sim service repos
git clone https://github.com/TidyBot-Services/arm_franka_sim_service.git
git clone https://github.com/TidyBot-Services/gripper_robotiq_sim_service.git
git clone https://github.com/TidyBot-Services/base_tidybot_sim_service.git
git clone https://github.com/TidyBot-Services/camera_realsense_sim_service.git

# Install them (editable mode so you can modify)
pip install -e arm_franka_sim_service/
pip install -e gripper_robotiq_sim_service/
pip install -e base_tidybot_sim_service/
pip install -e camera_realsense_sim_service/
```
