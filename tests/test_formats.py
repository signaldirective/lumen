"""Saving, backup and metadata tests."""

from __future__ import annotations

import os

import pytest
from PIL import Image
from PySide6.QtGui import QColor, QImage

from lumen import formats
from lumen.document import Document


def solid_image(width=64, height=48, color="red", alpha=255) -> QImage:
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor(color))
    if alpha != 255:
        image.fill(QColor(0, 0, 0, alpha))
    return image


def test_png_round_trip(tmp_path, qapp):
    target = tmp_path / "out.png"
    formats.save_image(solid_image(), target, preserve_metadata=False)
    image, frames = formats.load_image(target)

    assert target.exists()
    assert image.size() == solid_image().size()
    assert frames == 1
    assert image.pixelColor(1, 1) == QColor("red")


def test_jpeg_flattens_transparency(tmp_path, qapp):
    target = tmp_path / "out.jpg"
    transparent = QImage(32, 32, QImage.Format.Format_ARGB32)
    transparent.fill(QColor(0, 0, 0, 0))
    formats.save_image(transparent, target, quality=90, preserve_metadata=False)

    with Image.open(target) as saved:
        assert saved.mode in ("RGB", "L")
        assert saved.getpixel((16, 16))[0] > 240  # white backdrop


def test_save_document_backs_up_once_and_marks_saved(tmp_path, qapp, settings):
    target = tmp_path / "photo.png"
    formats.save_image(solid_image(color="red"), target, preserve_metadata=False)
    original_bytes = target.read_bytes()

    doc = Document()
    doc.load(solid_image(color="blue"), target)
    doc.clear_selection_pixels(QColor(0, 0, 0, 0))
    assert doc.is_dirty

    backup = formats.save_document(doc, target, settings)
    assert backup is not None
    assert backup.exists()
    assert backup.read_bytes() == original_bytes
    assert not doc.is_dirty
    # Saving again must not overwrite the pristine backup.
    doc.clear_selection_pixels(QColor(0, 0, 0, 0))
    assert formats.save_document(doc, target, settings) is None
    assert backup.read_bytes() == original_bytes


def test_exif_orientation_is_applied_on_load_and_removed_on_save(tmp_path, qapp):
    source = tmp_path / "phone.jpg"
    photo = Image.new("RGB", (60, 40), "green")
    exif = Image.Exif()
    exif[0x010F] = "LumenTest"  # Make
    exif[0x0112] = 6  # rotate 90 degrees
    photo.save(source, format="JPEG", exif=exif)

    image, _frames = formats.load_image(source, exif_rotate=True)
    assert image.width() == 40
    assert image.height() == 60

    target = tmp_path / "saved.jpg"
    formats.save_image(image, target, preserve_metadata=True, source=source)
    with Image.open(target) as saved:
        saved_exif = saved.getexif()
        assert saved_exif.get(0x010F) == "LumenTest"
        assert saved_exif.get(0x0112) is None


def test_metadata_can_be_dropped(tmp_path, qapp):
    source = tmp_path / "tagged.jpg"
    photo = Image.new("RGB", (20, 20), "green")
    exif = Image.Exif()
    exif[0x010F] = "LumenTest"
    photo.save(source, format="JPEG", exif=exif)

    target = tmp_path / "clean.jpg"
    formats.save_image(
        solid_image(20, 20, "green"), target, preserve_metadata=False, source=source
    )
    with Image.open(target) as saved:
        assert saved.getexif().get(0x010F) is None


def test_unsupported_suffix_is_refused(tmp_path, qapp):
    target = tmp_path / "weird.xyz"
    with pytest.raises(formats.ImageError, match="cannot save"):
        formats.save_image(solid_image(), target, preserve_metadata=False)
    assert not target.exists()


def test_new_files_are_world_readable(tmp_path, qapp):
    target = tmp_path / "perms.png"
    formats.save_image(solid_image(), target, preserve_metadata=False)
    mode = os.stat(target).st_mode & 0o777
    assert mode == 0o644


def test_backup_path(tmp_path):
    assert formats.backup_path(tmp_path / "a.jpg") == tmp_path / "a.jpg.bak"


def test_saving_as_svg_is_refused(tmp_path, qapp):
    with pytest.raises(formats.ImageError, match="cannot save .svg"):
        formats.save_image(
            solid_image(), tmp_path / "vector.svg", preserve_metadata=False
        )


def test_animated_backup_helper(tmp_path, qapp, settings):
    target = tmp_path / "anim.gif"
    target.write_bytes(b"GIF89a")
    backup = formats.backup_existing(target, settings)
    assert backup is not None
    assert backup.read_bytes() == b"GIF89a"
    assert formats.backup_existing(target, settings) is None
