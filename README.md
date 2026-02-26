# TidyBot Universe Servers

Simulated TidyBot environment — runs MuJoCo physics with protocol bridges that emulate real hardware servers, so the [agent_server](https://github.com/TidyBot-Services/agent_server) connects transparently to either sim or real hardware.

## Setup

```bash
git clone https://github.com/TidyBot-Services/sim.git
cd sim
conda create -n tidybot python=3.11
conda activate tidybot
./setup.sh
```

`setup.sh` handles everything: clones robocasa/robosuite, checks for sibling repos (agent_server, system_logger), installs Python packages, and patches TidyVerse robot assets into robosuite.

## Running

**Terminal 1 — sim server:**

```bash
mjpython -m sim_server
```

**Terminal 2 — agent server:**

```bash
cd agent_server && python3 server.py
```

The sim server starts MuJoCo and exposes four protocol bridges:

| Bridge | Protocol | Port(s) |
|--------|----------|---------|
| Base | multiprocessing.managers RPC | 50000 |
| Franka arm | ZMQ (msgpack) | 5555, 5556, 5557 |
| Gripper | ZMQ (JSON) | 5570, 5571 |
| Camera | WebSocket (binary JPEG) | 5580 |

The agent_server connects to these ports and exposes the unified REST/WebSocket API on port 8080.

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
├── sim_server/                 # MuJoCo sim server package
│   ├── server.py               #   Physics loop + command queue
│   ├── sim_robot.py            #   SimRobot: robosuite env wrapper
│   ├── config.py               #   Control tuning constants
│   ├── scenes.py               #   Custom scene registration
│   ├── bridges/                #   Protocol bridges
│   │   ├── base.py             #     RPC (port 50000)
│   │   ├── franka.py           #     ZMQ CMD/STATE/STREAM (5555-5557)
│   │   ├── gripper.py          #     ZMQ CMD/STATE (5570-5571)
│   │   └── camera.py           #     WebSocket (5580)
│   └── camera_server/          #   Camera HTTP server + YOLO client
├── tidybot_assets/             # TidyVerse robot definition
│   ├── assets/                 #   MuJoCo meshes, XML, controllers
│   └── setup.py                #   Patches assets into robosuite
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
