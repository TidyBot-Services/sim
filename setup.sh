#!/bin/bash
# Set up the sim repo: clone submodules and install TidyVerse robot.
set -e

echo "=== Initializing submodules ==="
git submodule update --init --recursive

echo ""
echo "=== Installing TidyVerse robot into robosuite ==="
python3 tidyverse/setup.py

echo ""
echo "=== Done ==="
echo "Start the server with: mjpython -m agent_server.server"
