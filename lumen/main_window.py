"""The Lumen main window: menus, actions, navigation and saving."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from PySide6.QtCore import QByteArray, QEvent, QPoint, QSettings, QSize, Qt, QTimer
from PySide6.QtGui import (
    QAction,
    QActionGroup,
    QColor,
    QGuiApplication,
    QIcon,
    QImage,
    QKeySequence,
    QMovie,
    QPalette,
)
from PySide6.QtWidgets import (
    QApplication,
    QFileDialog,
    QLabel,
    QMainWindow,
    QMessageBox,
    QStatusBar,
    QWidget,
)

from . import formats
from .canvas import Canvas
from .dialogs import AboutDialog, HelpDialog
from .document import Document
from .navigation import Navigator, Prefetcher
from .settings import APP_NAME, Settings
from .settings_dialog import SettingsDialog

RESOURCE_DIR = Path(__file__).parent / "resources"


def _dark_palette() -> QPalette:
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#1e1f22",
        QPalette.ColorRole.WindowText: "#e7e7e7",
        QPalette.ColorRole.Base: "#17181a",
        QPalette.ColorRole.AlternateBase: "#24262b",
        QPalette.ColorRole.Text: "#e7e7e7",
        QPalette.ColorRole.Button: "#2b2d31",
        QPalette.ColorRole.ButtonText: "#e7e7e7",
        QPalette.ColorRole.BrightText: "#ff6b6b",
        QPalette.ColorRole.ToolTipBase: "#2b2d31",
        QPalette.ColorRole.ToolTipText: "#e7e7e7",
        QPalette.ColorRole.Link: "#6aa9ff",
        QPalette.ColorRole.Highlight: "#3563c9",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#8b9099",
    }
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#6f747c"))
    palette.setColor(
        QPalette.ColorGroup.Disabled,
        QPalette.ColorRole.Highlight,
        QColor("#3a3d42"),
    )
    return palette


def _light_palette() -> QPalette:
    palette = QPalette()
    colors = {
        QPalette.ColorRole.Window: "#f2f2f2",
        QPalette.ColorRole.WindowText: "#1c1c1c",
        QPalette.ColorRole.Base: "#ffffff",
        QPalette.ColorRole.AlternateBase: "#f6f6f6",
        QPalette.ColorRole.Text: "#1c1c1c",
        QPalette.ColorRole.Button: "#e9e9e9",
        QPalette.ColorRole.ButtonText: "#1c1c1c",
        QPalette.ColorRole.BrightText: "#c0392b",
        QPalette.ColorRole.ToolTipBase: "#ffffff",
        QPalette.ColorRole.ToolTipText: "#1c1c1c",
        QPalette.ColorRole.Link: "#1a66cc",
        QPalette.ColorRole.Highlight: "#2f6fd0",
        QPalette.ColorRole.HighlightedText: "#ffffff",
        QPalette.ColorRole.PlaceholderText: "#8a8a8a",
    }
    for role, value in colors.items():
        palette.setColor(role, QColor(value))
    for role in (
        QPalette.ColorRole.WindowText,
        QPalette.ColorRole.Text,
        QPalette.ColorRole.ButtonText,
    ):
        palette.setColor(QPalette.ColorGroup.Disabled, role, QColor("#9a9a9a"))
    return palette


def _fallback_dark_preference() -> bool:
    """Best effort when the platform reports no colour scheme (bare Wayland)."""
    theme = os.environ.get("GTK_THEME", "")
    if "dark" in theme.lower():
        return True
    for name in ("gtk-4.0", "gtk-3.0"):
        ini = Path.home() / ".config" / name / "settings.ini"
        if not ini.exists():
            continue
        values = QSettings(str(ini), QSettings.Format.IniFormat)
        prefer = str(
            values.value("Settings/gtk-application-prefer-dark-theme", "")
        ).lower()
        theme_name = str(values.value("Settings/gtk-theme-name", "")).lower()
        if prefer in ("true", "1"):
            return True
        if "dark" in theme_name:
            return True
    try:
        result = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True,
            text=True,
            timeout=0.5,
            check=False,
        ).stdout.lower()
    except (OSError, subprocess.SubprocessError):
        result = ""
    if "dark" in result:
        return True
    if "light" in result:
        return False
    kde = QSettings(
        str(Path.home() / ".config" / "kdeglobals"), QSettings.Format.IniFormat
    )
    return "dark" in str(kde.value("General/ColorScheme", "")).lower()


def system_prefers_dark() -> bool:
    scheme = QGuiApplication.styleHints().colorScheme()
    if scheme == Qt.ColorScheme.Dark:
        return True
    if scheme == Qt.ColorScheme.Light:
        return False
    return _fallback_dark_preference()


class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.doc = Document(self)
        self.canvas = Canvas(self.doc, self.settings, self)
        self.navigator = Navigator(self.settings, self)
        self.prefetcher = Prefetcher(self.settings, self)

        self._movie: QMovie | None = None
        self._last_cursor = QPoint(0, 0)
        self._tool_actions: dict[str, QAction] = {}

        self.setWindowTitle(APP_NAME)
        self.setWindowIcon(QIcon(str(RESOURCE_DIR / "lumen.svg")))
        self.setCentralWidget(self.canvas)
        self.setAcceptDrops(True)
        self.doc.undo_budget_mb = int(self.settings.get("editing.undo_budget_mb", 512))

        self._build_actions()
        self._build_menus()
        self._build_status_bar()
        self._connect_signals()
        self._restore_geometry()
        self._apply_theme()
        self._update_actions()
        self._update_status()
        self._update_title()

        self._slideshow_timer = QTimer(self)
        self._slideshow_timer.timeout.connect(self._slideshow_tick)

    # -- construction -----------------------------------------------------
    def _action(
        self,
        text: str,
        slot,
        shortcut: str | None = None,
        *,
        checkable: bool = False,
        checked: bool = False,
    ) -> QAction:
        action = QAction(text, self)
        action.triggered.connect(lambda _checked=False, s=slot: s())
        if shortcut:
            action.setShortcut(QKeySequence(shortcut))
        action.setCheckable(checkable)
        if checkable:
            action.setChecked(checked)
        return action

    def _build_actions(self) -> None:
        self.act_open = self._action("&Open…", self.open_dialog, "Ctrl+O")
        self.act_save = self._action("&Save", self.save, "Ctrl+S")
        self.act_save_as = self._action("Save &As…", self.save_as, "Ctrl+Shift+S")
        self.act_settings = self._action("&Settings…", self.open_settings, "Ctrl+,")
        self.act_close = self._action("&Close", self.close, "Ctrl+Q")

        self.act_undo = self._action("&Undo", self.undo, "Ctrl+Z")
        self.act_redo = self._action("&Redo", self.redo, "Ctrl+Shift+Z")
        self.act_cut = self._action("Cu&t", self.cut, "Ctrl+X")
        self.act_copy = self._action("&Copy", self.copy, "Ctrl+C")
        self.act_paste = self._action("&Paste", self.paste, "Ctrl+V")
        self.act_delete = self._action("&Delete", self.delete_selection, "Delete")

        self.act_select_all = self._action("Select &All", self.select_all, "Ctrl+A")
        self.act_deselect = self._action("&Deselect", self.deselect, "Ctrl+Shift+A")
        self.act_crop = self._action("Cro&p", self.crop, "Ctrl+Shift+X")

        self.act_zoom_in = self._action("Zoom &In", self.zoom_in, "Ctrl++")
        self.act_zoom_in.setShortcuts([QKeySequence("Ctrl++"), QKeySequence("Ctrl+=")])
        self.act_zoom_out = self._action("Zoom &Out", self.zoom_out, "Ctrl+-")
        self.act_fit = self._action("&Fit to Window", self.fit_to_window, "Ctrl+0")
        self.act_actual = self._action("&Actual Size", self.actual_size, "Ctrl+1")
        self.act_fullscreen = self._action(
            "&Full Screen", self.toggle_fullscreen, "F11", checkable=True
        )
        self.act_slideshow = self._action(
            "&Slideshow", self._slideshow_toggled, "F5", checkable=True
        )
        self.act_play = self._action("&Pause Animation", self.toggle_animation, "Space")

        self.act_help = self._action("&Help", self.open_help, "F1")
        self.act_about = self._action("&About Lumen", self.open_about)

        group = QActionGroup(self)
        group.setExclusionPolicy(QActionGroup.ExclusionPolicy.ExclusiveOptional)
        for kind, label in (
            ("rect", "&Square"),
            ("ellipse", "&Circle"),
            ("freehand", "&Freehand"),
        ):
            action = QAction(label, self)
            action.setCheckable(True)
            action.toggled.connect(
                lambda checked, k=kind: self._select_tool(k, checked)
            )
            group.addAction(action)
            self._tool_actions[kind] = action
        self._tool_group = group

        self._add_shortcut_actions()

    def _add_shortcut_actions(self) -> None:
        # Shortcuts that are not visible in the menus.
        self.act_escape = self._action("Escape", self.handle_escape, "Esc")
        self.act_escape.setShortcutContext(Qt.ShortcutContext.WindowShortcut)

    def _build_menus(self) -> None:
        bar = self.menuBar()

        file_menu = bar.addMenu("&File")
        file_menu.addAction(self.act_open)
        file_menu.addAction(self.act_save)
        file_menu.addAction(self.act_save_as)
        file_menu.addSeparator()
        file_menu.addAction(self.act_settings)
        file_menu.addSeparator()
        file_menu.addAction(self.act_close)

        edit_menu = bar.addMenu("&Edit")
        edit_menu.addAction(self.act_undo)
        edit_menu.addAction(self.act_redo)
        edit_menu.addSeparator()
        edit_menu.addAction(self.act_cut)
        edit_menu.addAction(self.act_copy)
        edit_menu.addAction(self.act_paste)
        edit_menu.addAction(self.act_delete)

        select_menu = bar.addMenu("&Select")
        select_menu.addAction(self.act_select_all)
        select_menu.addAction(self.act_deselect)
        select_menu.addSeparator()
        selection_menu = select_menu.addMenu("&Selection")
        for kind, label in (
            ("rect", "&Square"),
            ("ellipse", "&Circle"),
            ("freehand", "&Freehand"),
        ):
            action = self._tool_actions[kind]
            action.setShortcut(
                QKeySequence({"rect": "S", "ellipse": "C", "freehand": "F"}[kind])
            )
            selection_menu.addAction(action)
        select_menu.addSeparator()
        select_menu.addAction(self.act_crop)

        view_menu = bar.addMenu("&View")
        view_menu.addAction(self.act_zoom_in)
        view_menu.addAction(self.act_zoom_out)
        view_menu.addAction(self.act_fit)
        view_menu.addAction(self.act_actual)
        view_menu.addSeparator()
        view_menu.addAction(self.act_play)
        view_menu.addAction(self.act_slideshow)
        view_menu.addAction(self.act_fullscreen)

        help_menu = bar.addMenu("&Help")
        help_menu.addAction(self.act_help)
        help_menu.addAction(self.act_about)

        self.addAction(self.act_escape)

    def _build_status_bar(self) -> None:
        bar = QStatusBar(self)
        bar.setSizeGripEnabled(True)
        self.setStatusBar(bar)

        self._status_name = QLabel()
        self._status_name.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        self._status_size = QLabel()
        self._status_zoom = QLabel()
        self._status_position = QLabel()
        for label in (self._status_size, self._status_zoom, self._status_position):
            label.setStyleSheet("color: palette(mid);")
            label.setMinimumWidth(60)
            label.setAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

        bar.addWidget(self._status_name, 1)
        bar.addPermanentWidget(self._status_size)
        bar.addPermanentWidget(self._status_zoom)
        bar.addPermanentWidget(self._status_position)
        bar.setVisible(bool(self.settings.get("appearance.show_status_bar", True)))

    def _connect_signals(self) -> None:
        self.doc.image_changed.connect(self._on_image_changed)
        self.doc.selection_changed.connect(self._update_actions)
        self.doc.state_changed.connect(self._on_state_changed)
        self.doc.path_changed.connect(self._update_title)

        self.canvas.advance.connect(self.step_image)
        self.canvas.zoom_changed.connect(self._on_zoom_changed)
        self.canvas.tool_changed.connect(self._on_tool_changed)
        self.canvas.escape_pressed.connect(self.handle_escape)
        self.canvas.cursor_moved.connect(self._on_cursor_moved)

        self.navigator.changed.connect(self._update_status)
        self.settings.changed.connect(self._on_settings_changed)
        QGuiApplication.clipboard().dataChanged.connect(self._update_actions)
        QGuiApplication.styleHints().colorSchemeChanged.connect(
            lambda *_: self._apply_theme()
        )

    # -- theme / geometry --------------------------------------------------
    def _apply_theme(self) -> None:
        mode = str(self.settings.get("appearance.theme", "system"))
        if mode == "system":
            dark = system_prefers_dark()
        else:
            dark = mode == "dark"
        app = QApplication.instance()
        if app is not None:
            app.setPalette(_dark_palette() if dark else _light_palette())
        self.canvas.set_dark(dark)

    def _restore_geometry(self) -> None:
        restored = False
        if self.settings.get("startup.restore_geometry", True):
            data = self.settings.get_bytes("window.geometry")
            if data:
                restored = self.restoreGeometry(QByteArray(data))
        if not restored:
            self.resize(1100, 760)

    def _save_geometry(self) -> None:
        if self.settings.get("startup.restore_geometry", True):
            self.settings.set_bytes("window.geometry", bytes(self.saveGeometry()))

    # -- loading -----------------------------------------------------------
    def open_dialog(self) -> None:
        start = self._start_directory()
        dialog = QFileDialog(self, "Open Image", str(start))
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptOpen)
        dialog.setFileMode(QFileDialog.FileMode.ExistingFile)
        dialog.setNameFilters(formats.image_filter().split(";;"))
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.resize(980, 640)
        if dialog.exec() != QFileDialog.DialogCode.Accepted:
            return
        files = dialog.selectedFiles()
        if files:
            self.open_path(Path(files[0]))

    def _start_directory(self) -> Path:
        if self.doc.path is not None:
            return self.doc.path.parent
        last = str(self.settings.get("startup.last_folder", ""))
        if last and Path(last).is_dir():
            return Path(last)
        pictures = Path.home() / "Pictures"
        return pictures if pictures.is_dir() else Path.home()

    def open_path(self, path: Path) -> None:
        path = Path(path).expanduser()
        if not path.exists():
            QMessageBox.critical(
                self, "Not found", f"{path}\n\nNo such file or folder."
            )
            return
        if path.is_dir():
            target_is_dir = True
        elif formats.is_supported(path):
            target_is_dir = False
        else:
            QMessageBox.critical(
                self, "Unsupported file", f"{path.name} is not a supported image."
            )
            return

        if not self._confirm_discard():
            return

        self.navigator.set_path(path)
        if target_is_dir:
            target = self.navigator.current()
            if target is None:
                QMessageBox.information(
                    self, "Empty folder", f"No supported images in {path}."
                )
                return
        else:
            target = path
        self._load(Path(target))

    def _load(self, path: Path) -> bool:
        exif_rotate = bool(self.settings.get("editing.exif_rotate", True))
        cached = (
            None
            if formats.extension(path) in formats.ANIMATED_EXTENSIONS
            else self.prefetcher.take(path)
        )
        try:
            if cached is not None and not cached.isNull():
                image, frames = cached, 1
            else:
                image, frames = formats.load_image(path, exif_rotate)
        except formats.ImageError as exc:
            QMessageBox.critical(self, "Could not open image", f"{path}\n\n{exc}")
            return False

        self._stop_movie()
        animated = frames > 1
        self.doc.load(image, path, animated=animated)
        self.doc.undo_budget_mb = int(self.settings.get("editing.undo_budget_mb", 512))

        if animated:
            movie = QMovie(str(path), QByteArray(), self)
            if movie.isValid():
                self._movie = movie
                movie.stateChanged.connect(self._on_movie_state)
                self.canvas.set_movie(movie)
            else:
                movie.deleteLater()
        else:
            self.canvas.set_movie(None)

        self.canvas.set_tool("none")
        self._sync_tool_actions()
        self.canvas.reset_view()
        self.navigator.set_current(path)
        self.settings.set("startup.last_folder", str(path.parent))
        self.prefetcher.request_neighbours(self.navigator)
        self._update_status()
        self._update_actions()
        self._update_title()
        self._update_play_action()
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)
        return True

    def _stop_movie(self) -> None:
        if self._movie is not None:
            self._movie.stop()
            try:
                self._movie.stateChanged.disconnect(self._on_movie_state)
            except (RuntimeError, TypeError):
                pass
            self._movie = None
        self.canvas.set_movie(None)

    def step_image(self, delta: int) -> None:
        if not self.doc.has_image:
            return
        if not self._confirm_discard():
            return
        target = self.navigator.step(delta)
        if target is None:
            self.statusBar().showMessage("End of folder", 2500)
            return
        self._load(target)

    # -- unsaved changes ---------------------------------------------------
    def _settle_floating(self) -> None:
        """Commit a floating layer before anything that reads the pixels."""
        if self.doc.floating is not None:
            self.doc.commit_floating()

    def _confirm_discard(self) -> bool:
        self._settle_floating()
        if not self.doc.is_dirty:
            return True
        if not self.settings.get("editing.prompt_unsaved", True):
            return True
        name = self.doc.path.name if self.doc.path else "this image"
        box = QMessageBox(self)
        box.setIcon(QMessageBox.Icon.Question)
        box.setWindowTitle("Unsaved changes")
        box.setText(f"Save changes to “{name}”?")
        box.setInformativeText("Your edits will be lost if you discard them.")
        save = box.addButton("Save", QMessageBox.ButtonRole.AcceptRole)
        discard = box.addButton("Discard", QMessageBox.ButtonRole.DestructiveRole)
        box.addButton(QMessageBox.StandardButton.Cancel)
        box.setDefaultButton(save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is save:
            return self.save()
        return clicked is discard

    # -- saving ------------------------------------------------------------
    def save(self) -> bool:
        if not self.doc.has_image:
            return False
        self._settle_floating()
        if (
            self.doc.animated
            or self.doc.path is None
            or formats.extension(self.doc.path) in {"svg", "svgz"}
        ):
            return self.save_as()
        return self._write_to(self.doc.path)

    def save_as(self) -> bool:
        if not self.doc.has_image:
            return False
        self._settle_floating()
        start = self._start_directory()
        stem = self.doc.path.stem if self.doc.path else "untitled"
        suffix = self._default_suffix()
        default = start / f"{stem}.{suffix}"

        dialog = QFileDialog(self, "Save As", str(start))
        dialog.setAcceptMode(QFileDialog.AcceptMode.AcceptSave)
        dialog.setFileMode(QFileDialog.FileMode.AnyFile)
        filters = formats.save_filter().split(";;")
        dialog.setNameFilters(filters)
        filter_index = {
            "png": 0,
            "jpg": 1,
            "jpeg": 1,
            "webp": 2,
            "tif": 3,
            "tiff": 3,
            "bmp": 4,
        }.get(suffix, 0)
        dialog.selectNameFilter(filters[filter_index])
        dialog.setOption(QFileDialog.Option.DontUseNativeDialog, True)
        dialog.resize(980, 640)
        dialog.selectFile(default.name)
        if dialog.exec() != QFileDialog.DialogCode.Accepted:
            return False
        files = dialog.selectedFiles()
        if not files:
            return False
        path = Path(files[0])
        if not path.suffix:
            path = path.with_suffix(
                f".{self._suffix_from_filter(dialog.selectedNameFilter())}"
            )
        return self._write_to(path)

    def _default_suffix(self) -> str:
        current = formats.extension(self.doc.path) if self.doc.path else ""
        mode = str(self.settings.get("editing.save_format", "original"))
        if mode == "png":
            return "png"
        if mode == "webp":
            return "webp"
        return (
            current
            if current in {"png", "jpg", "jpeg", "webp", "tif", "tiff", "bmp"}
            else "png"
        )

    @staticmethod
    def _suffix_from_filter(selected: str) -> str:
        lowered = selected.lower()
        if "jpeg" in lowered:
            return "jpg"
        if "webp" in lowered:
            return "webp"
        if "tiff" in lowered:
            return "tif"
        if "bmp" in lowered:
            return "bmp"
        return "png"

    def _write_to(self, path: Path) -> bool:
        path = Path(path)
        try:
            if self.doc.animated:
                if (
                    self.doc.path is not None
                    and path.resolve() == self.doc.path.resolve()
                ):
                    QMessageBox.warning(
                        self,
                        "Cannot overwrite animation",
                        "Saving over this file would replace the animation with a single "
                        "frame. Choose a different name.",
                    )
                    return False
                frame = self._current_frame()
                if frame is None:
                    raise formats.ImageError("No frame available to save")
                backup = formats.backup_existing(path, self.settings)
                formats.save_image(
                    frame,
                    path,
                    quality=int(self.settings.get("editing.lossy_quality", 90)),
                    preserve_metadata=False,
                )
                if backup is not None:
                    self.statusBar().showMessage(
                        f"Saved frame to {path.name} (backup: {backup.name})", 5000
                    )
                else:
                    self.statusBar().showMessage(f"Saved frame to {path.name}", 4000)
                return True

            backup = formats.save_document(self.doc, path, self.settings)
        except Exception as exc:  # noqa: BLE001 - surfaced to the user
            QMessageBox.critical(self, "Could not save image", f"{path}\n\n{exc}")
            return False

        try:
            self.navigator.refresh()
            self.navigator.set_current(path)
        except (OSError, ValueError):
            pass
        self.prefetcher.clear()
        self.prefetcher.request_neighbours(self.navigator)
        self._update_actions()
        self._update_title()
        self._update_status()
        if backup is not None:
            self.statusBar().showMessage(
                f"Saved {path.name} (backup: {backup.name})", 5000
            )
        else:
            self.statusBar().showMessage(f"Saved {path.name}", 3000)
        return True

    def _current_frame(self) -> QImage | None:
        if self._movie is not None:
            image = self._movie.currentPixmap().toImage()
            if not image.isNull():
                return image
        return self.doc.image

    # -- clipboard ---------------------------------------------------------
    def _fill_colour(self) -> QColor:
        mode = str(self.settings.get("editing.cut_fill", "transparent"))
        if mode == "white":
            return QColor(255, 255, 255)
        if mode == "custom":
            return QColor(str(self.settings.get("editing.cut_fill_color", "#ffffff")))
        return QColor(0, 0, 0, 0)

    @staticmethod
    def _clipboard_data():
        return QGuiApplication.clipboard().mimeData()

    def _clipboard_has_image(self) -> bool:
        data = self._clipboard_data()
        if data is None:
            return False
        if data.hasImage():
            return True
        if self.doc.clip is not None and not self.doc.clip.isNull():
            return True
        if data.hasUrls():
            for url in data.urls():
                if (
                    url.isLocalFile()
                    and formats.extension(url.toLocalFile())
                    in formats.SUPPORTED_EXTENSIONS
                ):
                    return True
        return False

    def _clipboard_image(self) -> QImage | None:
        clipboard = QGuiApplication.clipboard()
        data = clipboard.mimeData()
        if data is not None:
            if data.hasImage():
                image = clipboard.image()
                if not image.isNull():
                    return image
            if data.hasUrls():
                for url in data.urls():
                    if not url.isLocalFile():
                        continue
                    candidate = Path(url.toLocalFile())
                    if formats.is_supported(candidate):
                        try:
                            image, _frames = formats.load_image(candidate)
                            return image
                        except formats.ImageError:
                            continue
        if self.doc.clip is not None and not self.doc.clip.isNull():
            return self.doc.clip
        return None

    def copy(self) -> None:
        image = self.doc.copy_selection()
        if image is None:
            return
        QGuiApplication.clipboard().setImage(image)
        self._update_actions()
        self.statusBar().showMessage("Copied", 1800)

    def cut(self) -> None:
        image = self.doc.cut_selection(self._fill_colour())
        if image is None:
            return
        QGuiApplication.clipboard().setImage(image)
        self._update_actions()
        self.statusBar().showMessage("Cut", 1800)

    def paste(self) -> None:
        if not self.doc.has_image:
            return
        image = self._clipboard_image()
        if image is None or image.isNull():
            return
        if self.doc.floating is not None:
            self.doc.commit_floating()
        position = self._paste_position(image.size())
        if not self.doc.paste_image(image, position):
            return
        self.canvas.set_tool("none")
        self._sync_tool_actions()
        self._update_actions()
        self.statusBar().showMessage(
            "Drag inside the selection to position it · Enter to commit · Esc to cancel",
            6000,
        )

    def _paste_position(self, size: QSize) -> QPoint:
        mode = str(self.settings.get("editing.paste_position", "center"))
        if mode == "top_left":
            return QPoint(0, 0)
        if mode == "cursor":
            base = self._last_cursor
        else:
            base = self.canvas.viewport_center_image()
        position = QPoint(base.x() - size.width() // 2, base.y() - size.height() // 2)
        max_x = max(self.doc.width - size.width(), 0)
        max_y = max(self.doc.height - size.height(), 0)
        position.setX(max(0, min(position.x(), max_x)))
        position.setY(max(0, min(position.y(), max_y)))
        return position

    def delete_selection(self) -> None:
        if not self.doc.has_image:
            return
        if self.doc.floating is not None:
            self.doc.cancel_floating()
            return
        if not self.doc.has_selection:
            return
        self.doc.clear_selection_pixels(self._fill_colour())
        self.statusBar().showMessage("Deleted", 1800)

    # -- selection ---------------------------------------------------------
    def _select_tool(self, kind: str, checked: bool) -> None:
        self.canvas.set_tool(kind if checked else "none")
        if not checked and self.canvas.tool == kind:
            self.canvas.set_tool("none")

    def _on_tool_changed(self, tool: str) -> None:
        self._sync_tool_actions()
        hints = {
            "rect": "Drag to select a rectangle · Shift for a square · Alt from the centre",
            "ellipse": "Drag to select a circle or oval · Shift for a circle · Alt from the centre",
            "freehand": "Hold the left button and draw around the area to select",
        }
        if tool in hints:
            self.statusBar().showMessage(f"{hints[tool]} · Esc to finish", 6000)

    def _sync_tool_actions(self) -> None:
        tool = self.canvas.tool
        for kind, action in self._tool_actions.items():
            action.blockSignals(True)
            action.setChecked(kind == tool)
            action.blockSignals(False)

    def select_all(self) -> None:
        if not self.doc.has_image:
            return
        self.doc.select_all()
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def deselect(self) -> None:
        if self.doc.floating is not None:
            self.doc.cancel_floating()
        self.doc.clear_selection()

    def crop(self) -> None:
        if not self.doc.has_image:
            return
        was_fit = self.canvas.is_fit
        if not self.doc.crop(
            bool(self.settings.get("editing.deselect_after_crop", True))
        ):
            return
        if was_fit:
            self.canvas.fit_to_window()
        self._update_status()
        self.statusBar().showMessage("Cropped", 2000)

    # -- undo --------------------------------------------------------------
    def undo(self) -> None:
        if self.doc.floating is not None:
            self.doc.cancel_floating()
            self._update_actions()
            return
        was_fit = self.canvas.is_fit
        if self.doc.undo():
            if was_fit:
                self.canvas.fit_to_window()
            self._update_status()

    def redo(self) -> None:
        was_fit = self.canvas.is_fit
        if self.doc.redo():
            if was_fit:
                self.canvas.fit_to_window()
            self._update_status()

    # -- view --------------------------------------------------------------
    def zoom_in(self) -> None:
        self.canvas.zoom_by(1.25)

    def zoom_out(self) -> None:
        self.canvas.zoom_by(1 / 1.25)

    def fit_to_window(self) -> None:
        self.canvas.fit_to_window()

    def actual_size(self) -> None:
        self.canvas.actual_size()

    def toggle_fullscreen(self) -> None:
        if self.isFullScreen():
            self.showNormal()
            self.menuBar().setVisible(True)
            self.act_fullscreen.setChecked(False)
        else:
            self.showFullScreen()
            self.menuBar().setVisible(False)
            self.act_fullscreen.setChecked(True)
        self.canvas.setFocus(Qt.FocusReason.OtherFocusReason)

    def toggle_animation(self) -> None:
        self.canvas.toggle_animation()
        self._update_play_action()

    def _on_movie_state(self, _state) -> None:
        self._update_play_action()

    def _update_play_action(self) -> None:
        playing = (
            self._movie is not None and self._movie.state() == QMovie.MovieState.Running
        )
        self.act_play.setText("&Pause Animation" if playing else "&Play Animation")
        self.act_play.setEnabled(self._movie is not None and self._movie.isValid())

    # -- slideshow ---------------------------------------------------------
    def _slideshow_toggled(self) -> None:
        if self.act_slideshow.isChecked():
            if not self.doc.has_image:
                self.open_dialog()
                if not self.doc.has_image:
                    self.act_slideshow.setChecked(False)
                    return
            interval = int(self.settings.get("navigation.slideshow_interval", 5)) * 1000
            self._slideshow_timer.start(max(interval, 500))
            self.statusBar().showMessage(
                f"Slideshow: every {interval // 1000} s · F5 to stop", 4000
            )
        else:
            self._slideshow_timer.stop()
            self.statusBar().showMessage("Slideshow stopped", 2000)

    def _slideshow_tick(self) -> None:
        if not self.doc.has_image:
            self._stop_slideshow()
            return
        if self.doc.is_dirty and not self._confirm_discard():
            self._stop_slideshow()
            return
        if self.settings.get("navigation.slideshow_random", False):
            target = self.navigator.random_file()
        else:
            target = self.navigator.step(
                1, wrap=bool(self.settings.get("navigation.slideshow_loop", False))
            )
        if target is None:
            self._stop_slideshow()
            self.statusBar().showMessage("Slideshow finished", 3000)
            return
        self._load(target)

    def _stop_slideshow(self) -> None:
        self._slideshow_timer.stop()
        if self.act_slideshow.isChecked():
            self.act_slideshow.setChecked(False)

    # -- escape ------------------------------------------------------------
    def handle_escape(self) -> None:
        if self.doc.floating is not None:
            self.doc.cancel_floating()
            self._update_actions()
            return
        if self.doc.has_selection or self.canvas.tool != "none":
            self.doc.clear_selection()
            self.canvas.set_tool("none")
            self._sync_tool_actions()
            return
        if self.isFullScreen():
            self.toggle_fullscreen()

    # -- settings ----------------------------------------------------------
    def open_settings(self) -> None:
        SettingsDialog(self.settings, self).exec()

    def _on_settings_changed(self, key: str) -> None:
        if key == "" or key.startswith("appearance"):
            self._apply_theme()
            self.statusBar().setVisible(
                bool(self.settings.get("appearance.show_status_bar", True))
            )
        if (
            key == "" or key.startswith("navigation")
        ) and self._slideshow_timer.isActive():
            interval = int(self.settings.get("navigation.slideshow_interval", 5)) * 1000
            self._slideshow_timer.setInterval(max(interval, 500))
        if key == "" or key == "editing.undo_budget_mb":
            self.doc.undo_budget_mb = int(
                self.settings.get("editing.undo_budget_mb", 512)
            )
        self.canvas.settings_changed(key)
        self._update_actions()
        if key == "" or key.startswith("navigation"):
            self._update_status()

    # -- status / title ----------------------------------------------------
    def _on_image_changed(self) -> None:
        self._update_status()
        self._update_actions()

    def _on_state_changed(self) -> None:
        self._update_actions()
        self._update_title()
        self._update_status()
        if self.doc.is_dirty and self._slideshow_timer.isActive():
            self._stop_slideshow()
            self.statusBar().showMessage("Slideshow stopped: unsaved edits", 4000)

    def _on_zoom_changed(self, zoom: float, fit: bool) -> None:
        percent = zoom * 100
        text = f"{percent:.0f}%" if percent >= 10 else f"{percent:.1f}%"
        if fit:
            text = f"Fit · {text}"
        self._status_zoom.setText(text)

    def _on_cursor_moved(self, point: QPoint) -> None:
        self._last_cursor = point

    def _update_status(self) -> None:
        if not self.doc.has_image:
            self._status_name.setText("No image — press Ctrl+O to open one")
            self._status_size.setText("")
            self._status_zoom.setText("")
            self._status_position.setText("")
            return
        name = self.doc.path.name if self.doc.path else "Untitled"
        suffix = "  (animated)" if self.doc.animated else ""
        marker = "● " if self.doc.is_dirty else ""
        self._status_name.setText(f"{marker}{name}{suffix}")
        self._status_size.setText(f"{self.doc.width} × {self.doc.height}")
        self._on_zoom_changed(self.canvas.zoom, self.canvas.is_fit)
        count = self.navigator.count()
        if count:
            self._status_position.setText(f"{self.navigator.index() + 1} / {count}")
        else:
            self._status_position.setText("")

    def _update_title(self) -> None:
        if self.doc.path is not None:
            marker = " •" if self.doc.is_dirty else ""
            self.setWindowTitle(f"{self.doc.path.name}{marker} — {APP_NAME}")
        elif self.doc.has_image:
            self.setWindowTitle(
                f"Untitled{' •' if self.doc.is_dirty else ''} — {APP_NAME}"
            )
        else:
            self.setWindowTitle(APP_NAME)

    def _update_actions(self) -> None:
        has_image = self.doc.has_image
        editable = has_image and not self.doc.animated
        self.act_save.setEnabled(editable and self.doc.is_dirty)
        self.act_save_as.setEnabled(has_image)
        self.act_copy.setEnabled(editable)
        self.act_cut.setEnabled(editable)
        self.act_paste.setEnabled(editable and self._clipboard_has_image())
        self.act_delete.setEnabled(
            editable and (self.doc.has_selection or self.doc.floating is not None)
        )
        self.act_select_all.setEnabled(editable)
        self.act_deselect.setEnabled(
            editable and (self.doc.has_selection or self.doc.floating is not None)
        )
        for action in self._tool_actions.values():
            action.setEnabled(editable)
        self.act_crop.setEnabled(
            editable and (self.doc.has_selection or self.doc.floating is not None)
        )
        self.act_undo.setEnabled(editable and self.doc.can_undo)
        self.act_redo.setEnabled(editable and self.doc.can_redo)
        for action in (
            self.act_zoom_in,
            self.act_zoom_out,
            self.act_fit,
            self.act_actual,
        ):
            action.setEnabled(has_image)
        self.act_play.setEnabled(self._movie is not None and self._movie.isValid())

    # -- help --------------------------------------------------------------
    def open_help(self) -> None:
        HelpDialog(self).exec()

    def open_about(self) -> None:
        AboutDialog(self).exec()

    # -- events ------------------------------------------------------------
    def dragEnterEvent(self, event) -> None:
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        for url in event.mimeData().urls():
            if not url.isLocalFile():
                continue
            candidate = Path(url.toLocalFile())
            if candidate.is_dir() or formats.is_supported(candidate):
                self.open_path(candidate)
                event.acceptProposedAction()
                return
        event.ignore()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        action = getattr(self, "act_fullscreen", None)
        if (
            event.type() == QEvent.Type.WindowStateChange
            and not self.isFullScreen()
            and action is not None
        ):
            self.menuBar().setVisible(True)
            action.setChecked(False)

    def open_external(self, path: Path | None) -> None:
        self.raise_()
        self.activateWindow()
        if path is not None:
            self.open_path(Path(path))

    def closeEvent(self, event) -> None:
        if not self._confirm_discard():
            event.ignore()
            return
        self._stop_slideshow()
        self._stop_movie()
        self.prefetcher.clear()
        self._save_geometry()
        if self.doc.path is not None:
            self.settings.set("startup.last_folder", str(self.doc.path.parent))
        event.accept()
