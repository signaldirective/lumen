"""Image loading and saving, including metadata-safe writes.

Qt handles the pixels; Pillow is used when it is available so EXIF/ICC data can
be carried across a save.  Because Lumen rotates images by their EXIF
orientation on load, the orientation tag is always dropped on save to prevent a
second rotation when the file is next opened.
"""

from __future__ import annotations

import io
import os
import shutil
import tempfile
from pathlib import Path

from PySide6.QtCore import QBuffer, QIODevice
from PySide6.QtGui import QImage, QImageReader, QImageWriter

SUPPORTED_EXTENSIONS: tuple[str, ...] = (
    "png",
    "jpg",
    "jpeg",
    "jfif",
    "webp",
    "gif",
    "bmp",
    "tif",
    "tiff",
    "ico",
    "cur",
    "icns",
    "tga",
    "ppm",
    "pgm",
    "pbm",
    "xbm",
    "xpm",
    "svg",
    "svgz",
)

ANIMATED_EXTENSIONS = {"gif", "webp", "mng", "apng"}
LOSSY_EXTENSIONS = {"jpg", "jpeg", "webp"}

ORIENTATION_TAG = 0x0112


class ImageError(Exception):
    pass


def extension(path: Path | str) -> str:
    return Path(path).suffix.lstrip(".").lower()


def is_supported(path: Path | str) -> bool:
    return extension(path) in SUPPORTED_EXTENSIONS and Path(path).is_file()


def image_filter() -> str:
    patterns = " ".join(f"*.{ext}" for ext in SUPPORTED_EXTENSIONS)
    return f"Images ({patterns});;All files (*)"


def save_filter() -> str:
    return (
        "PNG image (*.png);;"
        "JPEG image (*.jpg *.jpeg);;"
        "WebP image (*.webp);;"
        "TIFF image (*.tif *.tiff);;"
        "BMP image (*.bmp)"
    )


def load_image(path: Path, exif_rotate: bool = True) -> tuple[QImage, int]:
    reader = QImageReader(str(path))
    reader.setAutoTransform(exif_rotate)
    image = reader.read()
    if image.isNull():
        raise ImageError(reader.errorString() or f"Could not read {path.name}")
    return image, max(1, reader.imageCount())


def _qimage_to_png_bytes(image: QImage) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        raise ImageError("Could not convert image data")
    data = bytes(buffer.data())
    buffer.close()
    return data


def _pillow_save(
    image: QImage,
    target: Path,
    fmt: str,
    quality: int,
    preserve_metadata: bool,
    source: Path | None,
) -> None:
    from PIL import Image

    pil = Image.open(io.BytesIO(_qimage_to_png_bytes(image)))
    pil.load()

    exif_bytes = None
    icc_profile = None
    if preserve_metadata and source is not None:
        try:
            with Image.open(source) as original:
                icc_profile = original.info.get("icc_profile")
                exif = original.getexif()
        except Exception:  # noqa: BLE001 - metadata is best effort
            exif = None
        if exif is not None:
            if exif.get(ORIENTATION_TAG) is not None:
                del exif[ORIENTATION_TAG]
            try:
                exif_bytes = exif.tobytes()
            except Exception:  # noqa: BLE001 - metadata is best effort
                exif_bytes = None

    if fmt == "jpeg":
        if pil.mode in ("RGBA", "LA", "P"):
            pil = pil.convert("RGBA")
            background = Image.new("RGB", pil.size, (255, 255, 255))
            background.paste(pil, mask=pil.split()[-1])
            pil = background
        else:
            pil = pil.convert("RGB")
        fmt_name = "JPEG"
    elif fmt == "webp":
        fmt_name = "WEBP"
    elif fmt == "tiff":
        fmt_name = "TIFF"
    elif fmt == "bmp":
        fmt_name = "BMP"
    else:
        fmt_name = "PNG"

    kwargs: dict = {}
    if fmt in ("jpeg", "webp"):
        kwargs["quality"] = int(quality)
    if fmt == "png":
        kwargs["optimize"] = True
    if exif_bytes:
        kwargs["exif"] = exif_bytes
    if icc_profile:
        kwargs["icc_profile"] = icc_profile

    pil.save(target, format=fmt_name, **kwargs)


def _qt_save(image: QImage, target: Path, fmt: str, quality: int) -> None:
    fmt_name = {"jpg": "jpeg", "jpeg": "jpeg", "tif": "tiff"}.get(fmt, fmt)
    writer = QImageWriter(str(target), fmt_name.encode("ascii"))
    if fmt in LOSSY_EXTENSIONS:
        writer.setQuality(int(quality))
    if not writer.write(image):
        raise ImageError(writer.errorString() or "Could not write image")


def save_image(
    image: QImage,
    target: Path,
    quality: int = 90,
    preserve_metadata: bool = True,
    source: Path | None = None,
) -> None:
    """Write ``image`` to ``target`` atomically, keeping the metadata if asked."""
    target = Path(target)
    fmt = extension(target)
    if fmt in ("jpg", "jpeg", "jpe", "jfif"):
        fmt = "jpeg"
    elif fmt in ("tif",):
        fmt = "tiff"
    elif fmt == "":
        fmt = "png"
    if fmt not in {"png", "jpeg", "webp", "bmp", "tiff"}:
        raise ImageError(
            f"Lumen cannot save .{fmt} files. Choose PNG, JPEG, WebP, TIFF or BMP."
        )

    target.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{target.stem}-",
        suffix=f".{fmt if fmt != 'jpeg' else 'jpg'}",
        dir=target.parent,
    )
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        if fmt == "bmp":
            _qt_save(image, tmp, fmt, quality)
        else:
            try:
                _pillow_save(image, tmp, fmt, quality, preserve_metadata, source)
            except Exception:  # noqa: BLE001 - Pillow is optional
                # Pillow missing or unhappy with this image: the Qt writer is
                # always available and handles every format Qt can read.
                _qt_save(image, tmp, fmt, quality)
        if target.exists():
            shutil.copymode(target, tmp)
        else:
            os.chmod(tmp, 0o644)
        os.replace(tmp, target)
    except Exception:
        try:
            tmp.unlink()
        except OSError:
            pass
        raise


def backup_path(target: Path) -> Path:
    return target.with_name(target.name + ".bak")


def backup_existing(target: Path, settings, create: bool = True) -> Path | None:
    """Copy an existing file to .bak once. Returns the backup if one was made."""
    target = Path(target)
    if not settings.get("editing.backup_on_overwrite", True):
        return None
    if not target.exists():
        return None
    backup = backup_path(target)
    if backup.exists():
        return None
    if not create:
        return backup
    try:
        shutil.copy2(target, backup)
    except OSError as exc:
        raise ImageError(f"Could not create backup: {exc}") from exc
    return backup


def save_document(document, target: Path, settings) -> Path | None:
    """Save a Document, backing up an existing file first.  Returns the backup."""
    target = Path(target)
    created_backup = backup_existing(target, settings)

    save_image(
        document.image,
        target,
        quality=settings.get("editing.lossy_quality", 90),
        preserve_metadata=settings.get("editing.preserve_metadata", True),
        source=document.path,
    )
    document.path = target
    document.mark_saved()
    return created_backup
