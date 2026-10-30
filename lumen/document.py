"""The edited image document: pixels, selection, floating layer, undo.

The document is deliberately free of any widget code so it can be unit tested
headlessly.  Pixels are always ARGB32 in *image* coordinates; the selection and
the outline of the floating layer use those same coordinates, which keeps the
canvas transform trivial.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import QObject, QPoint, QRect, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

EDIT_FORMAT = QImage.Format.Format_ARGB32
MAX_UNDO_STEPS = 20


@dataclass
class _Snapshot:
    image: QImage
    state: int


@dataclass
class Floating:
    """Pixels lifted out of (or pasted into) the image and not yet committed."""

    image: QImage
    offset: QPoint
    outline: QPainterPath
    before: QImage | None = None
    state: int = 0

    def rect(self) -> QRect:
        return QRect(self.offset, self.image.size())


class Document(QObject):
    image_changed = Signal()
    selection_changed = Signal()
    state_changed = Signal()  # dirty flag, undo/redo availability
    path_changed = Signal()

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._image: QImage | None = None
        self._path: Path | None = None
        self._selection: QPainterPath | None = None
        self.floating: Floating | None = None
        self.animated = False
        self.clip: QImage | None = None  # last image copied/cut, for lossless paste

        self._undo: list[_Snapshot] = []
        self._redo: list[_Snapshot] = []
        self._state = 0
        self._next_state = 1
        self._saved_state = 0
        self.undo_budget_mb = 512

    # -- basic state ------------------------------------------------------
    @property
    def image(self) -> QImage | None:
        return self._image

    @property
    def path(self) -> Path | None:
        return self._path

    @path.setter
    def path(self, value: Path | None) -> None:
        self._path = Path(value) if value else None
        self.path_changed.emit()

    @property
    def width(self) -> int:
        return self._image.width() if self._image else 0

    @property
    def height(self) -> int:
        return self._image.height() if self._image else 0

    @property
    def selection(self) -> QPainterPath | None:
        return self._selection

    @property
    def has_selection(self) -> bool:
        return self._selection is not None and not self._selection.isEmpty()

    @property
    def has_image(self) -> bool:
        return self._image is not None and not self._image.isNull()

    @property
    def is_dirty(self) -> bool:
        return self._state != self._saved_state

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    @property
    def undo_depth(self) -> int:
        return len(self._undo)

    @property
    def undo_bytes(self) -> int:
        return sum(snapshot.image.sizeInBytes() for snapshot in self._undo)

    @property
    def redo_bytes(self) -> int:
        return sum(snapshot.image.sizeInBytes() for snapshot in self._redo)

    def load(
        self, image: QImage, path: Path | None = None, animated: bool = False
    ) -> None:
        if image.format() != EDIT_FORMAT:
            image = image.convertToFormat(EDIT_FORMAT)
        self._image = image
        self._path = Path(path) if path else None
        self.animated = animated
        self._selection = None
        self.floating = None
        self._undo.clear()
        self._redo.clear()
        self._state = 0
        self._next_state = 1
        self._saved_state = 0
        self.image_changed.emit()
        self.selection_changed.emit()
        self.state_changed.emit()
        self.path_changed.emit()

    # -- undo -------------------------------------------------------------
    def _trim_undo(self) -> None:
        budget = max(1, int(self.undo_budget_mb)) * 1024 * 1024
        while len(self._undo) > MAX_UNDO_STEPS:
            self._undo.pop(0)
        while len(self._undo) > 1 and self.undo_bytes > budget:
            self._undo.pop(0)
        while len(self._redo) > MAX_UNDO_STEPS:
            self._redo.pop(0)
        while len(self._redo) > 1 and self.redo_bytes > budget:
            self._redo.pop(0)

    def _begin_edit(self) -> None:
        """Snapshot the current pixels and open a new undo step."""
        assert self.floating is None, "commit the floating layer before editing"
        if self._image is None:
            raise RuntimeError("no image loaded")
        self._push_snapshot(QImage(self._image), self._state)

    def _push_snapshot(self, image: QImage, state: int) -> None:
        self._undo.append(_Snapshot(image, state))
        self._redo.clear()
        self._trim_undo()
        self._state = self._next_state
        self._next_state += 1

    def _finish_edit(self) -> None:
        self.image_changed.emit()
        self.state_changed.emit()

    def undo(self) -> bool:
        if self.floating is not None:
            self.cancel_floating()
        if not self._undo:
            return False
        snapshot = self._undo.pop()
        self._redo.append(_Snapshot(QImage(self._image), self._state))
        self._image = snapshot.image
        self._state = snapshot.state
        self.selection_changed.emit()
        self._finish_edit()
        return True

    def redo(self) -> bool:
        if not self._redo:
            return False
        if self.floating is not None:
            self.cancel_floating()
        snapshot = self._redo.pop()
        self._undo.append(_Snapshot(QImage(self._image), self._state))
        self._image = snapshot.image
        self._state = snapshot.state
        self.selection_changed.emit()
        self._finish_edit()
        return True

    def mark_saved(self) -> None:
        self._saved_state = self._state
        self.state_changed.emit()

    # -- selection --------------------------------------------------------
    def set_selection(self, path: QPainterPath | None) -> None:
        if path is not None and path.isEmpty():
            path = None
        if path is not None and not self.has_image:
            path = None
        if path is not None:
            bounds = path.boundingRect().toAlignedRect().intersected(self._image.rect())
            if bounds.isEmpty():
                path = None
        self._selection = path
        self.selection_changed.emit()

    def clear_selection(self) -> None:
        if self._selection is not None:
            self._selection = None
            self.selection_changed.emit()

    def select_all(self) -> None:
        if not self.has_image:
            return
        path = QPainterPath()
        path.addRect(QRect(0, 0, self._image.width(), self._image.height()))
        self.set_selection(path)

    def selection_contains(self, point: QPoint) -> bool:
        return self.has_selection and self._selection.contains(point)

    # -- clipboard --------------------------------------------------------
    def _region_image(self) -> QImage | None:
        """Pixels covered by the selection (or the floating layer / whole image)."""
        if self.floating is not None:
            return self.floating.image.copy()
        if not self.has_image:
            return None
        image = self._image
        if not self.has_selection:
            return image.copy()

        bounds = (
            self._selection.boundingRect().toAlignedRect().intersected(image.rect())
        )
        if bounds.isEmpty():
            return None
        out = QImage(bounds.size(), EDIT_FORMAT)
        out.fill(Qt.GlobalColor.transparent)
        painter = QPainter(out)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setClipPath(self._selection.translated(-bounds.topLeft()))
        painter.drawImage(QPoint(0, 0), image, bounds)
        painter.end()
        return out

    def copy_selection(self) -> QImage | None:
        region = self._region_image()
        if region is not None and not region.isNull():
            self.clip = region.copy()
        return region

    def _fill_selection(self, color: QColor) -> None:
        if self.floating is not None:
            self.commit_floating()
        if not self.has_image:
            return
        self._begin_edit()
        painter = QPainter(self._image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        if self.has_selection:
            painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
            painter.fillPath(self._selection, color)
        else:
            painter.fillRect(self._image.rect(), color)
        painter.end()
        self._finish_edit()

    def clear_selection_pixels(self, color: QColor) -> None:
        """Cut/delete: replace the selected pixels with ``color`` (alpha = 0)."""
        self._fill_selection(color)

    def cut_selection(self, color: QColor) -> QImage | None:
        region = self.copy_selection()
        if region is not None:
            self._fill_selection(color)
        return region

    # -- floating layer ---------------------------------------------------
    def lift_selection(self) -> bool:
        """Detach the selected pixels so they can be dragged around."""
        if self.floating is not None or not self.has_image or not self.has_selection:
            return False
        region = self._region_image()
        if region is None or region.isNull():
            return False
        bounds = self._selection.boundingRect().toAlignedRect()
        outline = QPainterPath(self._selection)
        before = QImage(self._image)
        self._selection = None
        painter = QPainter(self._image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.fillPath(outline, QColor(0, 0, 0, 0))
        painter.end()
        self.floating = Floating(
            region, bounds.topLeft(), outline, before=before, state=self._state
        )
        self.selection_changed.emit()
        self.image_changed.emit()
        return True

    def paste_image(self, image: QImage, position: QPoint) -> bool:
        if image.isNull():
            return False
        if self.floating is not None:
            self.commit_floating()
        if not self.has_image:
            self.load(image)
        else:
            if image.format() != EDIT_FORMAT:
                image = image.convertToFormat(EDIT_FORMAT)
            outline = QPainterPath()
            outline.addRect(QRect(position, image.size()))
            self.floating = Floating(image, QPoint(position), outline)
            self._selection = None
            self.selection_changed.emit()
            self.image_changed.emit()
        return True

    def move_floating(self, delta: QPoint) -> None:
        if self.floating is None:
            return
        self.floating.offset += delta
        self.floating.outline.translate(delta)
        self.image_changed.emit()

    def commit_floating(self) -> None:
        floating = self.floating
        if floating is None:
            return
        if not self.has_image:
            self.floating = None
            return
        self.floating = None
        if floating.before is not None:
            self._push_snapshot(floating.before, floating.state)
        else:
            self._begin_edit()
        painter = QPainter(self._image)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)
        painter.drawImage(floating.offset, floating.image)
        painter.end()
        self._selection = floating.outline
        self.selection_changed.emit()
        self._finish_edit()

    def cancel_floating(self) -> None:
        if self.floating is None:
            return
        floating = self.floating
        self.floating = None
        if floating.before is not None:
            self._image = floating.before
        self._selection = None
        self.selection_changed.emit()
        self.image_changed.emit()

    def nudge_floating(self, dx: int, dy: int) -> bool:
        if self.floating is None:
            return False
        self.move_floating(QPoint(dx, dy))
        return True

    # -- crop -------------------------------------------------------------
    def crop(self, clear_selection: bool = True) -> bool:
        if not self.has_image:
            return False
        if self.floating is not None:
            self.commit_floating()
        if not self.has_selection:
            return False
        bounds = (
            self._selection.boundingRect()
            .toAlignedRect()
            .intersected(self._image.rect())
        )
        if bounds.isEmpty():
            return False
        self._begin_edit()
        self._image = self._image.copy(bounds)
        if clear_selection:
            self._selection = None
        else:
            self._selection = self._selection.translated(-bounds.topLeft())
        self.selection_changed.emit()
        self._finish_edit()
        return True
