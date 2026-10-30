"""Application entry point and single-instance handling."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from PySide6.QtCore import QByteArray
from PySide6.QtGui import QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from . import formats
from .main_window import MainWindow
from .settings import APP_ID, APP_NAME, VERSION, Settings

SERVER_NAME = "lumen-single-instance"


def _send_to_running_instance(path: Path | None) -> bool:
    socket = QLocalSocket()
    socket.connectToServer(SERVER_NAME)
    if not socket.waitForConnected(250):
        return False
    payload = str(path) if path else ""
    socket.write(payload.encode("utf-8"))
    socket.flush()
    socket.waitForBytesWritten(300)
    socket.disconnectFromServer()
    return True


def _folder_has_image(folder: Path) -> bool:
    try:
        with os.scandir(folder) as entries:
            for entry in entries:
                try:
                    if (
                        entry.is_file()
                        and Path(entry.name).suffix.lstrip(".").lower()
                        in formats.SUPPORTED_EXTENSIONS
                    ):
                        return True
                except OSError:
                    continue
    except OSError:
        return False
    return False


def _style_sheet() -> str:
    return """
    QMenuBar { padding: 2px 2px; }
    QMenuBar::item { padding: 4px 10px; border-radius: 4px; }
    QStatusBar::item { border: none; }
    QStatusBar { padding: 2px 6px; }
    QGroupBox { margin-top: 10px; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 3px; }
    """


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="lumen", description="Lumen — a small image viewer and light editor."
    )
    parser.add_argument("path", nargs="?", help="image file or folder to open")
    parser.add_argument("--version", action="version", version=f"Lumen {VERSION}")
    args = parser.parse_args(argv)

    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(APP_NAME)
    app.setApplicationVersion(VERSION)
    app.setDesktopFileName(APP_ID)
    app.setStyle("Fusion")
    app.setWindowIcon(QIcon(str(Path(__file__).parent / "resources" / "lumen.svg")))
    app.setStyleSheet(_style_sheet())

    settings = Settings()
    initial = Path(args.path).expanduser() if args.path else None

    if settings.get("startup.single_instance", True) and _send_to_running_instance(
        initial
    ):
        return 0

    window = MainWindow(settings)
    server: QLocalServer | None = None

    if settings.get("startup.single_instance", True):
        server = QLocalServer()
        QLocalServer.removeServer(SERVER_NAME)
        if server.listen(SERVER_NAME):

            def _on_connection() -> None:
                connection = server.nextPendingConnection() if server else None
                if connection is None:
                    return
                payload = QByteArray()
                if connection.waitForReadyRead(300):
                    payload = connection.readAll()
                connection.disconnectFromServer()
                text = bytes(payload).decode("utf-8", "replace").strip()
                window.open_external(Path(text) if text else None)

            server.newConnection.connect(_on_connection)
        else:
            server = None

    if initial is not None:
        window.open_path(initial)
    elif settings.get("startup.reopen_last_folder", True):
        last_text = str(settings.get("startup.last_folder", "")).strip()
        if last_text:
            last = Path(last_text)
            if last.is_dir() and _folder_has_image(last):
                window.open_path(last)

    window.show()
    code = app.exec()
    if server is not None:
        server.close()
        QLocalServer.removeServer(SERVER_NAME)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
