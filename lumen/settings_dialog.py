"""The Settings window: appearance, navigation, editing and startup."""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSignalBlocker, Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .settings import config_dir


class SettingsDialog(QDialog):
    def __init__(self, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.settings = settings
        self.setWindowTitle("Lumen Settings")
        self.resize(700, 700)
        self.setMinimumSize(560, 420)
        self.setModal(True)

        self._combos: list[tuple[QComboBox, str]] = []
        self._checks: list[tuple[QCheckBox, str]] = []
        self._spins: list[tuple[QSpinBox, str]] = []
        self._colors: list[tuple[QPushButton, str, object]] = []
        self._dependent: list[object] = []

        layout = QVBoxLayout(self)
        layout.setContentsMargins(14, 14, 14, 12)
        layout.setSpacing(10)

        tabs = QTabWidget()
        tabs.addTab(self._scrolled(self._appearance_tab()), "Appearance")
        tabs.addTab(self._scrolled(self._navigation_tab()), "Navigation")
        tabs.addTab(self._scrolled(self._editing_tab()), "Editing and Saving")
        tabs.addTab(self._scrolled(self._startup_tab()), "Startup")
        layout.addWidget(tabs, 1)

        footer = QHBoxLayout()
        defaults = QPushButton("Restore defaults")
        defaults.clicked.connect(self._restore_defaults)
        footer.addWidget(defaults)
        config = QPushButton("Open config folder")
        config.clicked.connect(self._open_config)
        footer.addWidget(config)
        footer.addStretch(1)
        hint = QLabel("Changes apply immediately.")
        hint.setStyleSheet("color: palette(mid);")
        footer.addWidget(hint)
        close = QPushButton("Close")
        close.setDefault(True)
        close.clicked.connect(self.accept)
        footer.addWidget(close)
        layout.addLayout(footer)

        self.settings.changed.connect(self._on_settings_changed)
        self._reload()

    @staticmethod
    def _scrolled(page: QWidget) -> QScrollArea:
        area = QScrollArea()
        area.setWidgetResizable(True)
        area.setFrameShape(QScrollArea.Shape.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        area.setWidget(page)
        return area

    # -- widget helpers ----------------------------------------------------
    @staticmethod
    def _group(title: str) -> tuple[QGroupBox, QFormLayout]:
        group = QGroupBox(title)
        form = QFormLayout(group)
        form.setContentsMargins(14, 16, 14, 10)
        form.setSpacing(8)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.AllNonFixedFieldsGrow)
        form.setLabelAlignment(
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter
        )
        return group, form

    def _page(self) -> tuple[QWidget, QVBoxLayout]:
        page = QWidget()
        layout = QVBoxLayout(page)
        layout.setContentsMargins(10, 10, 10, 8)
        layout.setSpacing(10)
        return page, layout

    def _combo(
        self,
        form: QFormLayout,
        label: str,
        key: str,
        options: list[tuple[str, str]],
        tooltip: str = "",
    ) -> QComboBox:
        combo = QComboBox()
        combo.setMinimumWidth(240)
        for text, value in options:
            combo.addItem(text, value)
        index = max(0, combo.findData(self.settings.get(key)))
        combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(
            lambda _index, c=combo, k=key: self.settings.set(k, c.currentData())
        )
        if tooltip:
            combo.setToolTip(tooltip)
        self._combos.append((combo, key))
        form.addRow(label, combo)
        return combo

    def _check(
        self, form: QFormLayout, label: str, key: str, tooltip: str = ""
    ) -> QCheckBox:
        box = QCheckBox(label)
        box.setChecked(bool(self.settings.get(key)))
        box.toggled.connect(lambda value, k=key: self.settings.set(k, bool(value)))
        if tooltip:
            box.setToolTip(tooltip)
        self._checks.append((box, key))
        form.addRow(box)
        return box

    def _spin(
        self,
        form: QFormLayout,
        label: str,
        key: str,
        minimum: int,
        maximum: int,
        suffix: str = "",
    ) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        spin.setSuffix(suffix)
        spin.setValue(int(self.settings.get(key, minimum)))
        spin.valueChanged.connect(lambda value, k=key: self.settings.set(k, int(value)))
        self._spins.append((spin, key))
        form.addRow(label, spin)
        return spin

    def _color(self, form: QFormLayout, label: str, key: str) -> QPushButton:
        button = QPushButton()
        button.setFixedWidth(96)

        def refresh() -> None:
            value = str(self.settings.get(key, "#ffffff"))
            color = QColor(value)
            text = "#ffffff" if color.lightness() < 128 else "#111111"
            button.setText(value)
            button.setStyleSheet(
                f"QPushButton {{ background-color: {value}; color: {text};"
                " border: 1px solid palette(mid); border-radius: 4px; padding: 3px; }"
                "QPushButton:disabled { background-color: palette(button);"
                " color: palette(mid); }"
            )

        def pick() -> None:
            current = QColor(str(self.settings.get(key, "#ffffff")))
            color = QColorDialog.getColor(current, self, "Choose colour")
            if color.isValid():
                self.settings.set(key, color.name())
                refresh()

        button.clicked.connect(pick)
        refresh()
        self._colors.append((button, key, refresh))
        form.addRow(label, button)
        return button

    @staticmethod
    def _note(text: str) -> QLabel:
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("color: palette(mid);")
        return label

    # -- tabs --------------------------------------------------------------
    def _appearance_tab(self) -> QWidget:
        page, layout = self._page()

        group, form = self._group("Theme")
        self._combo(
            form,
            "Colour theme",
            "appearance.theme",
            [("Follow system", "system"), ("Light", "light"), ("Dark", "dark")],
        )
        layout.addWidget(group)

        group, form = self._group("Canvas")
        backdrop = self._combo(
            form,
            "Behind transparency",
            "appearance.backdrop",
            [("Checkerboard", "checkerboard"), ("Solid colour", "solid")],
        )
        colour = self._color(form, "Backdrop colour", "appearance.backdrop_color")
        self._combo(
            form,
            "Scaling",
            "appearance.scaling",
            [("Smooth", "smooth"), ("Nearest neighbour (pixel art)", "nearest")],
        )
        form.addRow(
            self._note("Nearest neighbour keeps hard pixels at every zoom level.")
        )
        layout.addWidget(group)

        def update_backdrop(*_args) -> None:
            solid = self.settings.get("appearance.backdrop") == "solid"
            colour.setEnabled(solid)

        backdrop.currentIndexChanged.connect(update_backdrop)
        update_backdrop()
        self._dependent.append(update_backdrop)

        group, form = self._group("Interface")
        self._check(form, "Show the status bar", "appearance.show_status_bar")
        layout.addWidget(group)
        layout.addStretch(1)
        return page

    def _navigation_tab(self) -> QWidget:
        page, layout = self._page()

        group, form = self._group("Advancing")
        self._check(
            form,
            "Click to advance (left click next, right click previous)",
            "navigation.click_to_advance",
        )
        self._check(
            form, "Left and right arrow keys advance", "navigation.arrow_advance"
        )
        self._check(form, "Wrap around at the ends of the folder", "navigation.wrap")
        form.addRow(
            self._note(
                "Clicking never advances while a selection tool is armed or a pasted layer is floating."
            )
        )
        layout.addWidget(group)

        group, form = self._group("Folder")
        self._combo(
            form,
            "Order",
            "navigation.sort",
            [
                ("Natural name (img2 before img10)", "natural"),
                ("Name", "name"),
                ("Date modified", "date"),
                ("File size", "size"),
            ],
        )
        self._check(form, "Reverse order", "navigation.reverse")
        self._check(form, "Include subfolders", "navigation.include_subfolders")
        self._check(form, "Skip hidden files", "navigation.skip_hidden")
        self._combo(
            form,
            "Mouse wheel",
            "navigation.wheel",
            [("Go to next/previous image", "navigate"), ("Zoom", "zoom")],
            "Ctrl+wheel always zooms, whatever this is set to.",
        )
        self._check(form, "Preload neighbouring images", "navigation.preload")
        layout.addWidget(group)

        group, form = self._group("Slideshow")
        self._spin(form, "Interval", "navigation.slideshow_interval", 1, 120, " s")
        self._check(form, "Loop forever", "navigation.slideshow_loop")
        self._check(form, "Random order", "navigation.slideshow_random")
        layout.addWidget(group)

        group, form = self._group("Animated images")
        self._check(form, "Play automatically", "navigation.animation_autoplay")
        self._check(form, "Loop forever", "navigation.animation_loop")
        layout.addWidget(group)
        layout.addStretch(1)
        return page

    def _editing_tab(self) -> QWidget:
        page, layout = self._page()

        group, form = self._group("Safety")
        self._check(
            form,
            "Keep a .bak copy when overwriting a file",
            "editing.backup_on_overwrite",
        )
        self._check(
            form, "Ask before discarding unsaved changes", "editing.prompt_unsaved"
        )
        layout.addWidget(group)

        group, form = self._group("Saving")
        self._combo(
            form,
            "Save As default",
            "editing.save_format",
            [
                ("Same as the original", "original"),
                ("PNG", "png"),
                ("WebP", "webp"),
            ],
        )
        self._spin(form, "Lossy quality", "editing.lossy_quality", 1, 100)
        self._check(
            form, "Preserve EXIF and colour profile", "editing.preserve_metadata"
        )
        self._check(form, "Rotate by EXIF orientation on load", "editing.exif_rotate")
        form.addRow(
            self._note(
                "Save overwrites the original in its own format. The orientation tag is "
                "removed on save so the rotation is not applied twice."
            )
        )
        layout.addWidget(group)

        group, form = self._group("Editing")
        fill = self._combo(
            form,
            "Cut and delete fill",
            "editing.cut_fill",
            [
                ("Transparent", "transparent"),
                ("White", "white"),
                ("Custom colour", "custom"),
            ],
        )
        fill_colour = self._color(form, "Fill colour", "editing.cut_fill_color")
        self._combo(
            form,
            "Paste position",
            "editing.paste_position",
            [
                ("Centre of the view", "center"),
                ("Mouse cursor", "cursor"),
                ("Top-left corner", "top_left"),
            ],
        )
        self._check(form, "Deselect after cropping", "editing.deselect_after_crop")
        self._spin(form, "Undo history", "editing.undo_budget_mb", 64, 8192, " MB")
        layout.addWidget(group)

        def update_fill(*_args) -> None:
            fill_colour.setEnabled(self.settings.get("editing.cut_fill") == "custom")

        fill.currentIndexChanged.connect(update_fill)
        update_fill()
        self._dependent.append(update_fill)
        layout.addStretch(1)
        return page

    def _startup_tab(self) -> QWidget:
        page, layout = self._page()

        group, form = self._group("Window")
        self._check(
            form, "Restore window size and position", "startup.restore_geometry"
        )
        self._check(
            form, "Reopen the last folder on launch", "startup.reopen_last_folder"
        )
        self._check(
            form,
            "Single instance (open files in the running window)",
            "startup.single_instance",
        )
        layout.addWidget(group)

        group, form = self._group("Command line")
        form.addRow(
            self._note(
                "lumen [file|folder] opens a file or starts at the first image in a folder.\n"
                "Drag and drop works too."
            )
        )
        layout.addWidget(group)
        layout.addStretch(1)
        return page

    # -- state -------------------------------------------------------------
    def _reload(self) -> None:
        for combo, key in self._combos:
            index = combo.findData(self.settings.get(key))
            if index >= 0:
                with QSignalBlocker(combo):
                    combo.setCurrentIndex(index)
        for box, key in self._checks:
            with QSignalBlocker(box):
                box.setChecked(bool(self.settings.get(key)))
        for spin, key in self._spins:
            with QSignalBlocker(spin):
                spin.setValue(int(self.settings.get(key, spin.minimum())))
        for button, _key, refresh in self._colors:
            refresh()
        for callback in self._dependent:
            callback()

    def _on_settings_changed(self, key: str) -> None:
        if key == "":
            self._reload()

    def _restore_defaults(self) -> None:
        answer = QMessageBox.question(
            self,
            "Restore defaults",
            "Reset every setting to its default value?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer == QMessageBox.StandardButton.Yes:
            self.settings.reset()
            self._reload()

    def _open_config(self) -> None:
        target = config_dir()
        try:
            target.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.warning(self, "Config folder", str(exc))
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(Path(target))))
