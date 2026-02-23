#!/bin/bash
# Set up the sim repo: clone submodules and install TidyVerse robot.
set -e

echo "=== Initializing submodules ==="
git submodule update --init --recursive

echo ""
echo "=== Installing TidyVerse robot into robosuite ==="
python3 tidyverse/setup.py

echo ""
read -p "Download RoboCasa kitchen assets (~10 GB)? Required for kitchen environments. [y/N] " dl_answer
if [[ "$dl_answer" =~ ^[Yy]$ ]]; then
    echo "=== Downloading RoboCasa kitchen assets ==="
    python3 -m robocasa.scripts.download_kitchen_assets --types all
else
    echo "Skipped. You can download later with: python -m robocasa.scripts.download_kitchen_assets"
fi

echo ""
echo "=== Done ==="
echo "Start the server with: mjpython -m agent_server.server"
