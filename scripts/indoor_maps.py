"""Read-only floor discovery shared by local map scans and input checks."""
import os
from pathlib import Path


def _scene_entries(directory):
    if not directory:
        return []
    try:
        if not Path(directory).is_dir():
            return []
        return sorted(Path(directory).iterdir())
    except OSError:
        # Do not lose every scene when one folder is unreadable. An empty list
        # still blocks this scene's assembly/preflight as missing readable input.
        return []


def indoor_map_entries(directory):
    """DAS extensions identify indoor inputs, regardless of case or name length.

    Include non-files so input checks reject directories masquerading as floors.
    Engine compatibility is checked separately from scene classification.
    """
    return [path for path in _scene_entries(directory) if path.suffix.lower() == '.das']


def engine_indoor_map_entries(directory):
    """Entries the reviewed IndoorGeoInfo::LoadMap actually tries to import."""
    return [path for path in _scene_entries(directory)
            if path.name.endswith('das') and len(os.fsencode(path.name)) > 5]


def indoor_floor_files(directory):
    """Only regular floor files can identify a scene during map discovery."""
    try:
        return [path for path in indoor_map_entries(directory) if path.is_file()]
    except OSError:
        return []
