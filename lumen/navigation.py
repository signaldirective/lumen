"""Directory listing, ordering, next/previous movement and neighbour preloading."""

from __future__ import annotations

import random
from pathlib import Path

from PySide6.QtCore import QObject, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QImage, QImageReader

from . import formats


def natural_key(text: str) -> list:
    """Sort key that puts 'img2' before 'img10'."""
    parts: list = []
    number = ""
    for char in text.lower():
        if char.isdigit():
            number += char
            continue
        if number:
            parts.append((0, int(number)))
            number = ""
        parts.append((1, char))
    if number:
        parts.append((0, int(number)))
    return parts


class Navigator(QObject):
    changed = Signal()

    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._dir: Path | None = None
        self._files: list[Path] = []
        self._index = -1
        self._scan_key: tuple | None = None

    # -- listing ----------------------------------------------------------
    def files(self) -> list[Path]:
        self._ensure()
        return self._files

    def current(self) -> Path | None:
        self._ensure()
        return self._current_raw()

    def _current_raw(self) -> Path | None:
        if 0 <= self._index < len(self._files):
            return self._files[self._index]
        return None

    def index(self) -> int:
        self._ensure()
        return self._index

    def count(self) -> int:
        return len(self.files())

    def directory(self) -> Path | None:
        return self._dir

    def _current_key(self) -> tuple:
        return (
            str(self._dir) if self._dir else "",
            bool(self.settings.get("navigation.include_subfolders", False)),
            bool(self.settings.get("navigation.skip_hidden", True)),
            str(self.settings.get("navigation.sort", "natural")),
            bool(self.settings.get("navigation.reverse", False)),
        )

    def _ensure(self) -> None:
        key = self._current_key()
        if key != self._scan_key:
            self._rescan()

    def _rescan(self) -> None:
        current = self._current_raw() if self._scan_key is not None else None
        self._scan_key = self._current_key()
        files: list[Path] = []
        if self._dir and self._dir.is_dir():
            recursive = bool(self.settings.get("navigation.include_subfolders", False))
            skip_hidden = bool(self.settings.get("navigation.skip_hidden", True))
            try:
                walker = self._dir.rglob("*") if recursive else self._dir.iterdir()
                for entry in walker:
                    try:
                        if not entry.is_file() or not formats.is_supported(entry):
                            continue
                        if skip_hidden and any(
                            part.startswith(".")
                            for part in entry.relative_to(self._dir).parts
                        ):
                            continue
                        files.append(entry)
                    except OSError:
                        continue
            except OSError:
                files = []
        self._files = self._sorted(files)
        if current is not None:
            try:
                self._index = self._files.index(current)
            except ValueError:
                self._index = min(max(self._index, 0), max(len(self._files) - 1, 0))
        self._index = min(max(self._index, 0), max(len(self._files) - 1, 0))
        self.changed.emit()

    def _sorted(self, files: list[Path]) -> list[Path]:
        mode = str(self.settings.get("navigation.sort", "natural"))
        reverse = bool(self.settings.get("navigation.reverse", False))

        def mtime(path: Path) -> float:
            try:
                return path.stat().st_mtime
            except OSError:
                return 0.0

        def size(path: Path) -> int:
            try:
                return path.stat().st_size
            except OSError:
                return 0

        if mode == "date":
            files.sort(key=mtime, reverse=reverse)
        elif mode == "size":
            files.sort(key=size, reverse=reverse)
        elif mode == "name":
            files.sort(key=lambda p: p.name.casefold(), reverse=reverse)
        else:
            files.sort(
                key=lambda p: (natural_key(p.name), str(p).casefold()), reverse=reverse
            )
        return files

    # -- movement ---------------------------------------------------------
    def set_path(self, path: Path) -> None:
        path = Path(path).expanduser()
        if path.is_dir():
            self._dir = path
            self._index = 0
        else:
            self._dir = path.parent
            self._scan_key = None
            self._index = 0
            self._ensure()
            try:
                self._index = self._files.index(path.resolve())
            except ValueError:
                try:
                    self._index = self._files.index(path.absolute())
                except ValueError:
                    self._index = min(self._index, max(len(self._files) - 1, 0))
        self._scan_key = None
        self._ensure()
        self.changed.emit()

    def set_current(self, path: Path) -> None:
        path = Path(path).expanduser()
        if path.parent != self._dir:
            self.set_path(path)
            return
        self._ensure()
        try:
            self._index = self._files.index(path.absolute())
        except ValueError:
            try:
                self._index = self._files.index(path.resolve())
            except ValueError:
                self._rescan()

    def refresh(self) -> None:
        self._scan_key = None
        self._rescan()

    def step(self, delta: int, wrap: bool | None = None) -> Path | None:
        self._ensure()
        if not self._files:
            return None
        if wrap is None:
            wrap = bool(self.settings.get("navigation.wrap", True))
        target = self._index + delta
        if 0 <= target < len(self._files):
            self._index = target
        elif wrap:
            self._index = target % len(self._files)
        else:
            return None
        self.changed.emit()
        return self._files[self._index]

    def random_file(self) -> Path | None:
        self._ensure()
        if not self._files:
            return None
        if len(self._files) == 1:
            self._index = 0
        else:
            choices = [i for i in range(len(self._files)) if i != self._index]
            self._index = random.choice(choices)
        self.changed.emit()
        return self._files[self._index]


class _LoadTaskSignals(QObject):
    done = Signal(str, QImage)
    failed = Signal(str)


class _LoadTask(QRunnable):
    def __init__(self, path: Path, exif_rotate: bool) -> None:
        super().__init__()
        self.path = path
        self.exif_rotate = exif_rotate
        self.signals = _LoadTaskSignals()

    def run(self) -> None:
        try:
            reader = QImageReader(str(self.path))
            reader.setAutoTransform(self.exif_rotate)
            image = reader.read()
            if image.isNull():
                self.signals.failed.emit(str(self.path))
            else:
                self.signals.done.emit(str(self.path), image)
        except Exception:  # noqa: BLE001 - a failed prefetch is not fatal
            self.signals.failed.emit(str(self.path))


class Prefetcher(QObject):
    """Warms a tiny cache for the next/previous files."""

    def __init__(self, settings, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self._pool = QThreadPool(self)
        self._pool.setMaxThreadCount(1)
        self._cache: dict[str, QImage] = {}
        self._order: list[str] = []
        self._inflight: set[str] = set()

    def request(self, path: Path | None) -> None:
        if path is None or not self.settings.get("navigation.preload", True):
            return
        if not formats.is_supported(path):
            return
        if path.suffix.lower().lstrip(".") in formats.ANIMATED_EXTENSIONS:
            return
        key = str(path)
        if key in self._cache or key in self._inflight:
            return
        self._inflight.add(key)
        task = _LoadTask(path, bool(self.settings.get("editing.exif_rotate", True)))
        task.signals.done.connect(self._store)
        task.signals.failed.connect(self._forget)
        self._pool.start(task)

    def _store(self, key: str, image: QImage) -> None:
        self._inflight.discard(key)
        if image.sizeInBytes() > 256 * 1024 * 1024:
            return
        self._cache[key] = image
        self._order.append(key)
        while len(self._order) > 4:
            oldest = self._order.pop(0)
            self._cache.pop(oldest, None)

    def _forget(self, key: str) -> None:
        self._inflight.discard(key)

    def take(self, path: Path) -> QImage | None:
        key = str(path)
        image = self._cache.pop(key, None)
        if key in self._order:
            self._order.remove(key)
        return image

    def clear(self) -> None:
        self._cache.clear()
        self._order.clear()

    def request_neighbours(self, navigator: Navigator) -> None:
        if not self.settings.get("navigation.preload", True):
            return
        files = navigator.files()
        if not files:
            return
        index = navigator.index()
        if len(files) > 1:
            self.request(files[(index + 1) % len(files)])
        if len(files) > 2:
            self.request(files[(index - 1) % len(files)])
