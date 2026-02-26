# TidyBot Sim Server

Simulated TidyBot environment — runs MuJoCo physics with protocol bridges that emulate real hardware servers, so the agent_server connects transparently.

## Prerequisites

- Python 3.11+
- macOS (MuJoCo rendering requires `mjpython` for GUI mode)

## Setup

```bash
git clone https://github.com/TidyBot-Services/sim.git
cd sim

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate

# Run setup (clones deps, installs packages, patches robosuite)
./setup.sh
```

> **Note:** `setup.sh` clones robocasa/robosuite, checks for sibling agent_server/system_logger repos, installs Python packages, and runs `tidybot_assets/setup.py` to patch TidyVerse robot assets into robosuite.

## Running

### Sim server (MuJoCo + protocol bridges)

```bash
mjpython -m sim_server
```

This starts:
- MuJoCo physics loop on the main thread
- Base bridge (RPC on port 50000)
- Franka bridge (ZMQ on ports 5555-5557)
- Gripper bridge (ZMQ on ports 5570-5571)
- Camera bridge (WebSocket on port 5580)

### Agent server (separate terminal)

```bash
cd agent_server && python3 server.py
```

The agent_server connects to the bridges and exposes the unified REST/WebSocket API on port 8080.

### CLI options

```bash
mjpython -m sim_server \
    --task BananaTestKitchen \
    --robot TidyVerse \
    --layout 1 \
    --style 1 \
    --no-gui            # headless mode
```

## Project Structure

```
├── sim_server/             # MuJoCo sim server
│   ├── __main__.py         # Entry point
│   ├── server.py           # Physics loop + command queue
│   ├── sim_robot.py        # SimRobot wrapper around robosuite env
│   ├── config.py           # Control tuning constants
│   ├── scenes.py           # Custom scene registration
│   ├── bridges/            # Protocol bridges
│   │   ├── base.py         # multiprocessing.managers RPC (port 50000)
│   │   ├── franka.py       # ZMQ CMD/STATE/STREAM (ports 5555-5557)
│   │   ├── gripper.py      # ZMQ CMD/STATE (ports 5570-5571)
│   │   └── camera.py       # WebSocket (port 5580)
│   └── camera_server/      # Camera HTTP server + YOLO
├── tidybot_assets/         # TidyVerse robot definition
│   ├── assets/             # Meshes, XML, Python, controller config
│   └── setup.py            # Installs robot into robosuite
├── setup.sh                # One-command setup
└── requirements.txt        # Python dependencies
```

## Updating dependencies

```bash
cd robocasa && git pull origin main && cd ..
cd robosuite && git pull origin master && cd ..
python tidybot_assets/setup.py   # re-patch after update
```
