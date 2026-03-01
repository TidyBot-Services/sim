#!/bin/bash
# Set up the sim repo: clone dependencies and install TidyVerse robot.
set -e

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PARENT_DIR="$(dirname "$SCRIPT_DIR")"

echo "=== Cloning dependency repos ==="
if [ ! -d "robosuite" ]; then
    git clone https://github.com/ARISE-Initiative/robosuite.git
fi
if [ ! -d "robocasa" ]; then
    git clone https://github.com/robocasa/robocasa.git
fi

echo ""
echo "=== Checking for sibling repos ==="

# agent_server, system_logger, common, and hardware repos live in the parent directory
for repo_info in \
    "agent_server:https://github.com/TidyBot-Services/agent_server.git" \
    "system_logger:https://github.com/TidyBot-Services/system_logger.git" \
    "common:https://github.com/TidyBot-Services/common.git" \
    "hardware/arm_franka_service:https://github.com/TidyBot-Services/arm_franka_service.git" \
    "hardware/gripper_robotiq_service:https://github.com/TidyBot-Services/gripper_robotiq_service.git" \
    "hardware/base_tidybot_service:https://github.com/TidyBot-Services/base_tidybot_service.git" \
    "hardware/camera_realsense_service:https://github.com/TidyBot-Services/camera_realsense_service.git"; do

    repo_name="${repo_info%%:*}"
    repo_url="${repo_info#*:}"

    if [ -d "$PARENT_DIR/$repo_name" ]; then
        echo "Found $repo_name at $PARENT_DIR/$repo_name"
        if [ ! -d "$repo_name" ]; then
            ln -s "$PARENT_DIR/$repo_name" "$repo_name"
            echo "  -> Symlinked to ./$repo_name"
        fi
    elif [ -d "$repo_name" ]; then
        echo "Found $repo_name at ./$repo_name"
    else
        read -p "$repo_name not found. Clone it? [y/N] " answer
        if [[ "$answer" =~ ^[Yy]$ ]]; then
            git clone "$repo_url"
            echo "  -> Cloned $repo_name"
        else
            echo "  -> Skipped (you can clone it later)"
        fi
    fi
done

# Run common/setup.sh to create standard symlinks (logging_config.py, etc.)
if [ -d "$PARENT_DIR/common" ] && [ -x "$PARENT_DIR/common/setup.sh" ]; then
    echo "Running common/setup.sh..."
    bash "$PARENT_DIR/common/setup.sh"
fi

echo ""
echo "=== Installing native dependencies via conda ==="
conda install -y -c conda-forge llvmlite numba

echo ""
echo "=== Installing Python packages ==="
pip install -e robosuite/
pip install -e robocasa/
pip install -r requirements.txt

# Install system_logger (required by agent_server)
if [ -d "system_logger" ]; then
    pip install -e system_logger/
    echo "  Installed system_logger"
fi

# Install agent_server dependencies
if [ -d "agent_server" ] && [ -f "agent_server/requirements.txt" ]; then
    pip install -r agent_server/requirements.txt
    echo "  Installed agent_server dependencies"
fi

echo ""
echo "=== Installing TidyBot assets into robosuite ==="
python3 tidybot_assets/setup.py

echo ""
read -p "Download RoboCasa kitchen assets (~10 GB)? Required for kitchen environments. [y/N] " dl_answer
if [[ "$dl_answer" =~ ^[Yy]$ ]]; then
    echo "=== Downloading RoboCasa kitchen assets ==="
    cd robocasa
    python3 -m robocasa.scripts.download_kitchen_assets --type all
    cd ..
else
    echo "Skipped. You can download later with: python -m robocasa.scripts.download_kitchen_assets"
fi

echo ""
echo "=== Done ==="
echo "Start the sim server with: mjpython -m sim_server"
