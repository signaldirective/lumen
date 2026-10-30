"""About, licence and help windows."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon, QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QTextBrowser,
    QVBoxLayout,
)

from .settings import AUTHOR, EMAIL, VERSION

RESOURCE_DIR = Path(__file__).parent / "resources"


def _icon_pixmap(size: int = 96) -> QPixmap:
    path = RESOURCE_DIR / "lumen.svg"
    pixmap = QPixmap(str(path))
    if pixmap.isNull():
        return pixmap
    return pixmap.scaled(
        size,
        size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )


class AboutDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("About Lumen")
        self.setModal(True)
        self.setMinimumWidth(420)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(28, 24, 28, 20)
        layout.setSpacing(10)

        header = QHBoxLayout()
        icon = QLabel()
        pixmap = _icon_pixmap(88)
        if not pixmap.isNull():
            icon.setPixmap(pixmap)
            header.addWidget(icon, 0, Qt.AlignmentFlag.AlignTop)
        text = QVBoxLayout()
        name = QLabel("Lumen")
        name.setStyleSheet("font-size: 26px; font-weight: 600;")
        tagline = QLabel("A small image viewer and light editor.")
        tagline.setWordWrap(True)
        text.addWidget(name)
        text.addWidget(tagline)
        header.addSpacing(14)
        header.addLayout(text, 1)
        layout.addLayout(header)

        details = QLabel(
            f"Version {VERSION}<br>"
            f'Created by {AUTHOR} &lt;<a href="mailto:{EMAIL}">{EMAIL}</a>&gt;<br>'
            "Released under the MIT licence."
        )
        details.setOpenExternalLinks(True)
        details.setTextFormat(Qt.TextFormat.RichText)
        details.setWordWrap(True)
        layout.addWidget(details)

        import PySide6

        about_qt = QLabel(
            f"Built with Qt {PySide6.QtCore.qVersion()} and PySide6 {PySide6.__version__}."
        )
        about_qt.setStyleSheet("color: palette(mid);")
        about_qt.setWordWrap(True)
        layout.addWidget(about_qt)

        buttons = QHBoxLayout()
        licence = QPushButton("Licence")
        licence.clicked.connect(lambda: LicenceDialog(self).exec())
        buttons.addWidget(licence)
        buttons.addStretch(1)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        buttons.addWidget(close)
        layout.addSpacing(6)
        layout.addLayout(buttons)

    def showEvent(self, event) -> None:
        super().showEvent(event)
        icon = _icon_pixmap(64)
        if not icon.isNull():
            self.setWindowIcon(QIcon(icon))


class LicenceDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("MIT Licence")
        self.resize(620, 520)
        layout = QVBoxLayout(self)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setPlainText(_licence_text())
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        layout.addWidget(buttons)


def _licence_text() -> str:
    for candidate in (RESOURCE_DIR / "LICENSE", RESOURCE_DIR.parent.parent / "LICENSE"):
        try:
            return candidate.read_text(encoding="utf-8")
        except OSError:
            continue
    return "MIT License\n\nCopyright (c) 2026 Ro Black"


class HelpDialog(QDialog):
    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Lumen Help")
        self.resize(780, 620)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        browser = QTextBrowser()
        browser.setOpenExternalLinks(True)
        browser.setFrameShape(QTextBrowser.Shape.NoFrame)
        browser.setHtml((RESOURCE_DIR / "help.html").read_text(encoding="utf-8"))
        browser.setStyleSheet("QTextBrowser { padding: 8px 16px; }")
        layout.addWidget(browser)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        buttons.accepted.connect(self.accept)
        buttons.setContentsMargins(12, 8, 12, 12)
        layout.addWidget(buttons)
