"""Persistent application settings for Lumen.

Settings live in a single JSON file under the XDG config directory so they are
easy to inspect, back up and reset.  Every key has a default; loading merges the
stored file over the defaults, so new settings added in later versions appear
automatically.
"""

from __future__ import annotations

import base64
import copy
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, Signal

APP_NAME = "Lumen"
APP_ID = "lumen"
VERSION = "0.1.0"
AUTHOR = "Ro Black"
EMAIL = "signaldirective@gmail.com"

DEFAULTS: dict[str, Any] = {
    "appearance": {
        "theme": "system",  # system | light | dark
        "backdrop": "checkerboard",  # checkerboard | solid
        "backdrop_color": "#2f3236",
        "scaling": "smooth",  # smooth | nearest
        "show_status_bar": True,
    },
    "navigation": {
        "click_to_advance": False,
        "arrow_advance": True,
        "wrap": True,
        "include_subfolders": False,
        "skip_hidden": True,
        "sort": "natural",  # natural | name | date | size
        "reverse": False,
        "wheel": "navigate",  # navigate | zoom
        "preload": True,
        "slideshow_interval": 5,
        "slideshow_loop": False,
        "slideshow_random": False,
        "animation_autoplay": True,
        "animation_loop": True,
    },
    "editing": {
        "backup_on_overwrite": True,
        "prompt_unsaved": True,
        "exif_rotate": True,
        "preserve_metadata": True,
        "save_format": "original",  # original | png | webp
        "lossy_quality": 90,
        "cut_fill": "transparent",  # transparent | white | custom
        "cut_fill_color": "#ffffff",
        "paste_position": "center",  # center | cursor | top_left
        "deselect_after_crop": True,
        "undo_budget_mb": 512,
    },
    "startup": {
        "restore_geometry": True,
        "reopen_last_folder": True,
        "single_instance": True,
        "last_folder": "",
    },
}


def config_dir() -> Path:
    override = os.environ.get("LUMEN_CONFIG_DIR")
    if override:
        return Path(override).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME")
    root = Path(base).expanduser() if base else Path.home() / ".config"
    return root / APP_ID


def config_file() -> Path:
    return config_dir() / "settings.json"


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    merged = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(merged.get(key), dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged


class Settings(QObject):
    """JSON-backed settings with change notification.

    ``changed`` carries the dotted key that changed, or ``""`` when the whole
    settings tree was replaced (reset).
    """

    changed = Signal(str)

    def __init__(self, path: Path | None = None, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._path = Path(path) if path else config_file()
        self._data = copy.deepcopy(DEFAULTS)
        self.load()

    # -- io ---------------------------------------------------------------
    def load(self) -> None:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            raw = {}
        if isinstance(raw, dict):
            self._data = _deep_merge(DEFAULTS, raw)

    def save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(
                prefix=".settings-", suffix=".json", dir=self._path.parent
            )
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(self._data, handle, indent=2, sort_keys=True)
                handle.write("\n")
            os.replace(tmp, self._path)
        except OSError:
            # A read-only or missing config directory must never crash the app.
            pass

    def reset(self) -> None:
        self._data = copy.deepcopy(DEFAULTS)
        self.save()
        self.changed.emit("")

    # -- access -----------------------------------------------------------
    def get(self, dotted: str, fallback: Any = None) -> Any:
        node: Any = self._data
        for part in dotted.split("."):
            if not isinstance(node, dict) or part not in node:
                return fallback
            node = node[part]
        return node

    def set(self, dotted: str, value: Any) -> None:
        parts = dotted.split(".")
        node = self._data
        for part in parts[:-1]:
            child = node.get(part)
            if not isinstance(child, dict):
                child = {}
                node[part] = child
            node = child
        if node.get(parts[-1]) == value:
            return
        node[parts[-1]] = value
        self.save()
        self.changed.emit(dotted)

    def get_bytes(self, dotted: str) -> bytes | None:
        encoded = self.get(dotted)
        if not isinstance(encoded, str) or not encoded:
            return None
        try:
            return base64.b64decode(encoded)
        except ValueError:
            return None

    def set_bytes(self, dotted: str, value: bytes) -> None:
        self.set(dotted, base64.b64encode(value).decode("ascii"))
