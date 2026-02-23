#!/usr/bin/env python3
"""Install TidyVerse robot into a vanilla robosuite checkout.

Run from the repo root:
    python tidyverse/setup.py

Copies asset files and patches robosuite's registration modules so that
``TidyVerse`` is available as a robot name.  Safe to run multiple times
(skips files that already exist, patches only if marker not found).
"""

import os
import shutil
import sys

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
ROBOSUITE = os.path.join(REPO_ROOT, "robosuite", "robosuite")

MARKER = "# --- TidyVerse ---"


def _copy(src, dst):
    """Copy file or directory, skip if destination already exists."""
    if os.path.exists(dst):
        print(f"  skip (exists): {os.path.relpath(dst, REPO_ROOT)}")
        return
    os.makedirs(os.path.dirname(dst), exist_ok=True)
    if os.path.isdir(src):
        shutil.copytree(src, dst)
    else:
        shutil.copy2(src, dst)
    print(f"  copy: {os.path.relpath(dst, REPO_ROOT)}")


def _patch(filepath, marker, lines):
    """Append lines to a Python file if marker is not already present."""
    with open(filepath, "r") as f:
        content = f.read()
    if marker in content:
        print(f"  skip (patched): {os.path.relpath(filepath, REPO_ROOT)}")
        return
    with open(filepath, "a") as f:
        f.write(f"\n{marker}\n")
        for line in lines:
            f.write(line + "\n")
    print(f"  patch: {os.path.relpath(filepath, REPO_ROOT)}")


def _insert_after(filepath, after_pattern, new_lines, marker):
    """Insert lines after a matching pattern in a file."""
    with open(filepath, "r") as f:
        content = f.read()
    if marker in content:
        print(f"  skip (patched): {os.path.relpath(filepath, REPO_ROOT)}")
        return
    lines = content.split("\n")
    result = []
    inserted = False
    for line in lines:
        result.append(line)
        if not inserted and after_pattern in line:
            result.append(marker)
            result.extend(new_lines)
            inserted = True
    if not inserted:
        # Fallback: append at end
        result.append(marker)
        result.extend(new_lines)
    with open(filepath, "w") as f:
        f.write("\n".join(result))
    print(f"  patch: {os.path.relpath(filepath, REPO_ROOT)}")


def copy_assets():
    """Copy TidyVerse XML, meshes, and controller config into robosuite."""
    print("Copying assets...")

    # Base XML + meshes
    _copy(
        os.path.join(ASSETS_DIR, "bases", "tidyverse_base.xml"),
        os.path.join(ROBOSUITE, "models", "assets", "bases", "tidyverse_base.xml"),
    )
    _copy(
        os.path.join(ASSETS_DIR, "bases", "meshes", "tidyverse_base"),
        os.path.join(ROBOSUITE, "models", "assets", "bases", "meshes", "tidyverse_base"),
    )

    # Gripper XML + meshes
    _copy(
        os.path.join(ASSETS_DIR, "grippers", "tidyverse_robotiq_85.xml"),
        os.path.join(ROBOSUITE, "models", "assets", "grippers", "tidyverse_robotiq_85.xml"),
    )
    _copy(
        os.path.join(ASSETS_DIR, "grippers", "meshes", "tidyverse_robotiq_85"),
        os.path.join(ROBOSUITE, "models", "assets", "grippers", "meshes", "tidyverse_robotiq_85"),
    )

    # Python modules
    _copy(
        os.path.join(ASSETS_DIR, "python", "tidyverse_base.py"),
        os.path.join(ROBOSUITE, "models", "bases", "tidyverse_base.py"),
    )
    _copy(
        os.path.join(ASSETS_DIR, "python", "tidyverse_robotiq_85_gripper.py"),
        os.path.join(ROBOSUITE, "models", "grippers", "tidyverse_robotiq_85_gripper.py"),
    )
    _copy(
        os.path.join(ASSETS_DIR, "python", "tidyverse_robot.py"),
        os.path.join(ROBOSUITE, "models", "robots", "tidyverse_robot.py"),
    )

    # Controller config
    _copy(
        os.path.join(ASSETS_DIR, "controllers", "default_tidyverse.json"),
        os.path.join(ROBOSUITE, "controllers", "config", "robots", "default_tidyverse.json"),
    )


def patch_registration():
    """Patch robosuite __init__.py files to register TidyVerse."""
    print("Patching registration...")

    # 1. models/bases/__init__.py — import + mapping
    _insert_after(
        os.path.join(ROBOSUITE, "models", "bases", "__init__.py"),
        "from .omron_mobile_base import OmronMobileBase",
        ["from .tidyverse_base import TidyVerseBase"],
        MARKER,
    )
    _insert_after(
        os.path.join(ROBOSUITE, "models", "bases", "__init__.py"),
        '"OmronMobileBase": OmronMobileBase',
        ['    "TidyVerseBase": TidyVerseBase,'],
        MARKER + " mapping",
    )

    # 2. models/grippers/__init__.py — import + mapping
    _insert_after(
        os.path.join(ROBOSUITE, "models", "grippers", "__init__.py"),
        "from .robotiq_85_gripper import Robotiq85Gripper",
        ["from .tidyverse_robotiq_85_gripper import TidyVerseRobotiq85Gripper"],
        MARKER,
    )
    _insert_after(
        os.path.join(ROBOSUITE, "models", "grippers", "__init__.py"),
        '"Robotiq85Gripper": Robotiq85Gripper',
        ['    "TidyVerseRobotiq85Gripper": TidyVerseRobotiq85Gripper,'],
        MARKER + " mapping",
    )

    # 3. models/robots/compositional.py — import the TidyVerse class
    _patch(
        os.path.join(ROBOSUITE, "models", "robots", "compositional.py"),
        MARKER,
        ["from .tidyverse_robot import TidyVerse  # noqa: F401"],
    )

    # 4. robots/__init__.py — register as WheeledRobot
    _insert_after(
        os.path.join(ROBOSUITE, "robots", "__init__.py"),
        '"PandaOmron": WheeledRobot',
        ['    "TidyVerse": WheeledRobot,'],
        MARKER,
    )


def main():
    if not os.path.isdir(ROBOSUITE):
        print(f"Error: robosuite not found at {ROBOSUITE}")
        print("Run 'git submodule update --init' first.")
        sys.exit(1)

    copy_assets()
    patch_registration()
    print("Done! TidyVerse robot installed into robosuite.")


if __name__ == "__main__":
    main()
