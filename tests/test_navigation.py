"""Folder listing and navigation behaviour."""

from __future__ import annotations

import os

from PySide6.QtGui import QColor, QImage

from lumen.navigation import Navigator, natural_key


def write_image(path, color="red") -> None:
    image = QImage(8, 8, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    assert image.save(str(path))


def test_natural_sort_key_orders_numbers_by_value():
    names = ["img10.png", "img2.png", "img1.png", "cat.png"]
    assert sorted(names, key=natural_key) == [
        "cat.png",
        "img1.png",
        "img2.png",
        "img10.png",
    ]


def test_folder_listing_uses_natural_order(tmp_path, qapp, settings):
    for name in ("img10.png", "img2.png", "img1.png"):
        write_image(tmp_path / name)
    (tmp_path / "notes.txt").write_text("not an image")

    navigator = Navigator(settings)
    navigator.set_path(tmp_path)

    assert [p.name for p in navigator.files()] == ["img1.png", "img2.png", "img10.png"]
    assert navigator.count() == 3


def test_step_wraps_in_both_directions(tmp_path, qapp, settings):
    for name in ("a.png", "b.png", "c.png"):
        write_image(tmp_path / name)
    navigator = Navigator(settings)
    navigator.set_path(tmp_path / "a.png")

    assert navigator.step(-1).name == "c.png"
    assert navigator.step(1).name == "a.png"
    assert navigator.step(1).name == "b.png"


def test_step_without_wrap_stops_at_the_edges(tmp_path, qapp, settings):
    for name in ("a.png", "b.png"):
        write_image(tmp_path / name)
    settings.set("navigation.wrap", False)
    navigator = Navigator(settings)
    navigator.set_path(tmp_path / "a.png")

    assert navigator.step(-1) is None
    assert navigator.step(1).name == "b.png"
    assert navigator.step(1) is None


def test_hidden_files_are_skipped_by_default(tmp_path, qapp, settings):
    write_image(tmp_path / "shown.png")
    write_image(tmp_path / ".hidden.png")

    navigator = Navigator(settings)
    navigator.set_path(tmp_path)

    assert [p.name for p in navigator.files()] == ["shown.png"]


def test_subfolders_are_included_only_when_enabled(tmp_path, qapp, settings):
    write_image(tmp_path / "top.png")
    (tmp_path / "nested").mkdir()
    write_image(tmp_path / "nested" / "deep.png")

    navigator = Navigator(settings)
    navigator.set_path(tmp_path)
    assert [p.name for p in navigator.files()] == ["top.png"]

    settings.set("navigation.include_subfolders", True)
    assert [p.name for p in navigator.files()] == ["deep.png", "top.png"]


def test_reverse_order(tmp_path, qapp, settings):
    for name in ("a.png", "b.png"):
        write_image(tmp_path / name)
    settings.set("navigation.reverse", True)

    navigator = Navigator(settings)
    navigator.set_path(tmp_path)

    assert [p.name for p in navigator.files()] == ["b.png", "a.png"]


def test_sort_by_size(tmp_path, qapp, settings):
    small = tmp_path / "small.png"
    write_image(small, "red")
    large = tmp_path / "large.png"
    write_image(large, "blue")
    os.truncate(large, small.stat().st_size + 1024)
    settings.set("navigation.sort", "size")

    navigator = Navigator(settings)
    navigator.set_path(tmp_path)

    assert [p.name for p in navigator.files()] == ["small.png", "large.png"]


def test_current_index_follows_set_current(tmp_path, qapp, settings):
    for name in ("a.png", "b.png", "c.png"):
        write_image(tmp_path / name)
    navigator = Navigator(settings)
    navigator.set_path(tmp_path / "a.png")

    navigator.set_current(tmp_path / "c.png")
    assert navigator.index() == 2
    assert navigator.current().name == "c.png"
