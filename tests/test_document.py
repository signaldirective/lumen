"""Pixel-level tests for the editing document."""

from __future__ import annotations

import pytest
from PySide6.QtCore import QPoint, QRect, QSize
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath

from lumen.document import Document


def make_image(width=100, height=80) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    painter = QPainter(image)
    painter.fillRect(QRect(10, 10, 30, 20), QColor("blue"))
    painter.end()
    return image


def rect_selection(x, y, width, height) -> QPainterPath:
    path = QPainterPath()
    path.addRect(QRect(x, y, width, height))
    return path


@pytest.fixture
def doc(qapp):
    document = Document()
    document.load(make_image(), None)
    return document


def test_copy_selection_keeps_only_selected_pixels(doc):
    doc.set_selection(rect_selection(10, 10, 30, 20))
    region = doc.copy_selection()

    assert region is not None
    assert region.size() == QSize(30, 20)
    assert region.pixelColor(5, 5) == QColor("blue")
    assert doc.clip is not None


def test_copy_without_selection_copies_the_whole_image(doc):
    region = doc.copy_selection()

    assert region.width() == 100
    assert region.height() == 80
    assert region.pixelColor(0, 0) == QColor("red")
    assert region.pixelColor(15, 15) == QColor("blue")


def test_cut_clears_the_selection_to_transparent(doc):
    doc.set_selection(rect_selection(10, 10, 30, 20))
    doc.cut_selection(QColor(0, 0, 0, 0))

    assert doc.image.pixelColor(15, 15).alpha() == 0
    assert doc.image.pixelColor(5, 5) == QColor("red")
    assert doc.is_dirty
    assert doc.clip is not None


def test_delete_does_not_touch_the_clipboard_copy(doc):
    doc.set_selection(rect_selection(10, 10, 30, 20))
    doc.copy_selection()
    original = doc.clip
    doc.clear_selection_pixels(QColor(0, 0, 0, 0))

    assert doc.clip is original
    assert doc.image.pixelColor(15, 15).alpha() == 0


def test_paste_commit_places_pixels_and_keeps_the_selection(doc):
    doc.set_selection(rect_selection(10, 10, 30, 20))
    region = doc.copy_selection()

    assert doc.paste_image(region, QPoint(50, 40))
    assert doc.floating is not None
    assert not doc.has_selection
    doc.commit_floating()

    assert doc.floating is None
    assert doc.image.pixelColor(55, 45) == QColor("blue")
    assert doc.has_selection
    assert doc.selection.contains(QPoint(55, 45))


def test_cancel_floating_paste_restores_the_canvas(doc):
    doc.set_selection(rect_selection(10, 10, 30, 20))
    region = doc.copy_selection()
    doc.paste_image(region, QPoint(60, 50))
    doc.cancel_floating()

    assert doc.floating is None
    assert doc.image.pixelColor(65, 55) == QColor("red")
    assert not doc.is_dirty


def test_lift_and_cancel_restores_the_original_pixels(doc):
    doc.set_selection(rect_selection(10, 10, 30, 20))
    assert doc.lift_selection()
    assert doc.image.pixelColor(15, 15).alpha() == 0
    assert doc.floating is not None

    doc.cancel_floating()

    assert doc.image.pixelColor(15, 15) == QColor("blue")
    assert not doc.is_dirty


def test_lift_move_commit_moves_pixels_and_clears_the_source(doc):
    doc.set_selection(rect_selection(10, 10, 30, 20))
    doc.lift_selection()
    doc.move_floating(QPoint(40, 30))
    doc.commit_floating()

    assert doc.image.pixelColor(15, 15).alpha() == 0  # source cleared
    assert doc.image.pixelColor(55, 45) == QColor("blue")  # destination painted
    assert doc.is_dirty


def test_undo_and_redo_round_trip_with_dirty_state(doc):
    doc.mark_saved()
    doc.set_selection(rect_selection(10, 10, 30, 20))
    doc.cut_selection(QColor(0, 0, 0, 0))
    assert doc.is_dirty

    assert doc.undo()
    assert doc.image.pixelColor(15, 15) == QColor("blue")
    assert not doc.is_dirty

    assert doc.redo()
    assert doc.image.pixelColor(15, 15).alpha() == 0
    assert doc.is_dirty


def test_crop_uses_the_selection_bounds(doc):
    doc.set_selection(rect_selection(10, 10, 30, 20))
    assert doc.crop()

    assert doc.width == 30
    assert doc.height == 20
    assert doc.image.pixelColor(5, 5) == QColor("blue")
    assert not doc.has_selection
    assert doc.undo()
    assert doc.width == 100


def test_undo_budget_evicts_old_snapshots(qapp):
    document = Document()
    document.load(make_image(200, 200), None)
    document.undo_budget_mb = 1
    document.set_selection(rect_selection(0, 0, 50, 50))
    for _ in range(30):
        document.clear_selection_pixels(QColor(0, 0, 0, 0))

    assert document.undo_depth < 30
    assert document.undo_bytes <= 1024 * 1024 + 4 * 200 * 200


def test_selection_outside_the_image_is_rejected(doc):
    doc.set_selection(rect_selection(500, 500, 10, 10))
    assert not doc.has_selection


def test_crop_can_keep_a_translated_selection(doc):
    doc.set_selection(rect_selection(10, 10, 30, 20))
    assert doc.crop(clear_selection=False)

    assert doc.has_selection
    assert doc.selection.boundingRect().toAlignedRect() == QRect(0, 0, 30, 20)
    assert doc.selection.contains(QPoint(15, 10))
