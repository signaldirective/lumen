"""End-to-end widget tests for the main window."""

from __future__ import annotations

from PySide6.QtCore import QPoint, QRect, Qt
from PySide6.QtGui import QColor, QGuiApplication, QImage, QPainter

from lumen.main_window import MainWindow


def make_photo(path, width=80, height=60):
    image = QImage(width, height, QImage.Format.Format_ARGB32)
    image.fill(QColor("red"))
    painter = QPainter(image)
    painter.fillRect(QRect(10, 10, 20, 15), QColor("blue"))
    painter.end()
    assert image.save(str(path))


def make_window(qtbot, settings):
    window = MainWindow(settings)
    qtbot.addWidget(window)
    window.resize(600, 420)
    window.show()
    return window


def test_open_selection_cut_copy_paste_save(qtbot, tmp_path, settings):
    source = tmp_path / "photo.png"
    make_photo(source)
    window = make_window(qtbot, settings)
    window.open_path(source)

    assert window.doc.width == 80
    assert window.doc.height == 60
    assert source.name in window.windowTitle()

    window.select_all()
    window.copy()
    clipboard_image = QGuiApplication.clipboard().image()
    assert clipboard_image.width() == 80
    assert clipboard_image.height() == 60

    window.cut()
    assert window.doc.image.pixelColor(15, 12).alpha() == 0
    assert window.doc.is_dirty
    assert "•" in window.windowTitle()

    assert window.save()
    assert (tmp_path / "photo.png.bak").exists()
    assert not window.doc.is_dirty
    assert "•" not in window.windowTitle()

    # Round-trip through the clipboard back onto the canvas.
    window.paste()
    assert window.doc.floating is not None
    window.doc.commit_floating()
    assert window.doc.image.pixelColor(15, 12) == QColor("blue")
    window.save()
    assert window.doc.image.pixelColor(15, 12) == QColor("blue")


def test_undo_returns_to_the_saved_state(qtbot, tmp_path, settings):
    source = tmp_path / "photo.png"
    make_photo(source)
    window = make_window(qtbot, settings)
    window.open_path(source)

    window.select_all()
    window.cut()
    assert window.doc.is_dirty
    window.undo()
    assert not window.doc.is_dirty
    assert window.doc.image.pixelColor(15, 12) == QColor("blue")
    assert not window.act_undo.isEnabled()


def test_crop_shortcut_is_only_enabled_with_a_selection(qtbot, tmp_path, settings):
    source = tmp_path / "photo.png"
    make_photo(source)
    window = make_window(qtbot, settings)
    window.open_path(source)

    assert not window.act_crop.isEnabled()
    window.select_all()
    assert window.act_crop.isEnabled()


def test_rect_tool_creates_a_selection_by_dragging(qtbot, tmp_path, settings):
    source = tmp_path / "photo.png"
    make_photo(source)
    window = make_window(qtbot, settings)
    window.open_path(source)
    window.canvas.set_tool("rect")

    qtbot.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(280, 190))
    qtbot.mouseMove(window.canvas, QPoint(320, 230))
    qtbot.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(320, 230))

    assert window.doc.has_selection
    assert window.act_crop.isEnabled()


def test_escape_clears_the_selection_and_tool(qtbot, tmp_path, settings):
    source = tmp_path / "photo.png"
    make_photo(source)
    window = make_window(qtbot, settings)
    window.open_path(source)
    window.canvas.set_tool("freehand")
    window.select_all()
    assert window.doc.has_selection

    window.handle_escape()

    assert not window.doc.has_selection
    assert window.canvas.tool == "none"
    assert not window.act_crop.isEnabled()


def test_click_to_advance_moves_to_the_next_image(qtbot, tmp_path, settings):
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    make_photo(first, 40, 30)
    make_photo(second, 40, 30)
    settings.set("navigation.click_to_advance", True)
    window = make_window(qtbot, settings)
    window.open_path(first)
    qtbot.wait(20)

    qtbot.mouseClick(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(30, 30))

    assert window.doc.path.name == "b.png"
    assert window.doc.width == 40


def test_arrow_key_advance_can_be_disabled(qtbot, tmp_path, settings):
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    make_photo(first, 40, 30)
    make_photo(second, 40, 30)
    settings.set("navigation.arrow_advance", True)
    window = make_window(qtbot, settings)
    window.open_path(first)

    qtbot.keyClick(window.canvas, Qt.Key.Key_Right)
    assert window.doc.path.name == "b.png"

    settings.set("navigation.click_to_advance", False)
    settings.set("navigation.arrow_advance", False)
    qtbot.keyClick(window.canvas, Qt.Key.Key_Left)
    assert window.doc.path.name == "b.png"


def test_arrow_keys_nudge_a_floating_layer_instead_of_advancing(
    qtbot, tmp_path, settings
):
    source = tmp_path / "photo.png"
    make_photo(source)
    settings.set("navigation.arrow_advance", True)
    window = make_window(qtbot, settings)
    window.open_path(source)
    window.select_all()
    window.copy()
    window.paste()
    assert window.doc.floating is not None
    offset = QPoint(window.doc.floating.offset)

    qtbot.keyClick(window.canvas, Qt.Key.Key_Right)

    assert window.doc.floating is not None
    assert window.doc.floating.offset.x() == offset.x() + 1
    assert window.doc.path.name == "photo.png"
    window.doc.cancel_floating()


def test_save_as_writes_a_new_file_and_updates_the_title(qtbot, tmp_path, settings):
    source = tmp_path / "photo.png"
    make_photo(source)
    window = make_window(qtbot, settings)
    window.open_path(source)
    window.select_all()
    window.crop()

    target = tmp_path / "cropped.png"
    assert window._write_to(target)
    assert target.exists()
    assert window.doc.path == target
    assert window.doc.width == 80
    assert "cropped.png" in window.windowTitle()


def test_new_window_starts_empty(qtbot, settings):
    window = make_window(qtbot, settings)
    assert not window.doc.has_image
    assert "No image" in window._status_name.text()
    assert not window.act_save_as.isEnabled()
    assert not window.act_copy.isEnabled()


def test_save_includes_a_floating_paste(qtbot, tmp_path, settings):
    source = tmp_path / "photo.png"
    make_photo(source)
    window = make_window(qtbot, settings)
    window.open_path(source)

    window.select_all()
    window.copy()
    window.paste()
    assert window.doc.floating is not None
    window.doc.move_floating(QPoint(5, 5))

    assert window.save()
    assert window.doc.floating is None
    assert not window.doc.is_dirty

    from lumen import formats

    saved, _frames = formats.load_image(source)
    assert saved.pixelColor(20, 20) == QColor("blue")


def test_animated_gif_opens_read_only(qtbot, tmp_path, settings):
    from PIL import Image

    gif = tmp_path / "anim.gif"
    first = Image.new("RGB", (24, 16), "red")
    second = Image.new("RGB", (24, 16), "blue")
    first.save(gif, save_all=True, append_images=[second], duration=60, loop=0)

    window = make_window(qtbot, settings)
    window.open_path(gif)

    assert window.doc.animated
    assert window.act_play.isEnabled()
    assert window.act_save_as.isEnabled()
    assert not window.act_copy.isEnabled()
    assert not window.act_save.isEnabled()
    assert not window.act_select_all.isEnabled()
    window._stop_movie()


def test_click_to_advance_is_suspended_while_a_tool_is_armed(qtbot, tmp_path, settings):
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    make_photo(first, 40, 30)
    make_photo(second, 40, 30)
    settings.set("navigation.click_to_advance", True)
    window = make_window(qtbot, settings)
    window.open_path(first)
    window.canvas.set_tool("rect")
    qtbot.wait(20)

    qtbot.mouseClick(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(300, 210))

    assert window.doc.path.name == "a.png"
    assert window.canvas.tool == "rect"


def test_wheel_navigates_when_set_to_navigate(qtbot, tmp_path, settings):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    make_photo(first, 40, 30)
    make_photo(second, 40, 30)
    window = make_window(qtbot, settings)
    window.open_path(first)

    event = QWheelEvent(
        QPointF(10, 10),
        QPointF(10, 10),
        QPoint(0, 0),
        QPoint(0, -120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.NoModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(window.canvas, event)

    assert window.doc.path.name == "b.png"


def test_wheel_with_ctrl_zooms_instead_of_advancing(qtbot, tmp_path, settings):
    from PySide6.QtCore import QPointF
    from PySide6.QtGui import QWheelEvent
    from PySide6.QtWidgets import QApplication

    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    make_photo(first, 40, 30)
    make_photo(second, 40, 30)
    window = make_window(qtbot, settings)
    window.open_path(first)
    before = window.canvas.zoom

    event = QWheelEvent(
        QPointF(200, 200),
        QPointF(200, 200),
        QPoint(0, 0),
        QPoint(0, 120),
        Qt.MouseButton.NoButton,
        Qt.KeyboardModifier.ControlModifier,
        Qt.ScrollPhase.NoScrollPhase,
        False,
    )
    QApplication.sendEvent(window.canvas, event)

    assert window.canvas.zoom > before
    assert window.doc.path.name == "a.png"


def test_tool_actions_are_mutually_exclusive(qtbot, tmp_path, settings):
    source = tmp_path / "photo.png"
    make_photo(source)
    window = make_window(qtbot, settings)
    window.open_path(source)

    window._tool_actions["rect"].trigger()
    assert window.canvas.tool == "rect"
    window._tool_actions["ellipse"].trigger()
    assert window.canvas.tool == "ellipse"
    assert window._tool_actions["ellipse"].isChecked()
    assert not window._tool_actions["rect"].isChecked()
    window._tool_actions["ellipse"].trigger()
    assert window.canvas.tool == "none"
    assert not window._tool_actions["ellipse"].isChecked()


def test_settings_reset_while_dialog_is_open(qtbot, settings):
    from lumen.settings_dialog import SettingsDialog

    settings.set("appearance.theme", "dark")
    dialog = SettingsDialog(settings)
    qtbot.addWidget(dialog)
    dialog.show()
    settings.reset()
    qtbot.wait(20)
    assert settings.get("appearance.theme") == "system"


def test_freehand_drag_creates_a_lasso_selection(qtbot, tmp_path, settings):
    source = tmp_path / "photo.png"
    make_photo(source)
    window = make_window(qtbot, settings)
    window.open_path(source)
    window.canvas.set_tool("freehand")

    points = [
        QPoint(280, 195),
        QPoint(305, 195),
        QPoint(325, 210),
        QPoint(300, 232),
        QPoint(275, 215),
    ]
    qtbot.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=points[0])
    for point in points[1:]:
        qtbot.mouseMove(window.canvas, point)
    qtbot.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=points[-1])

    assert window.doc.has_selection
    assert window.canvas.tool == "freehand"
    assert window.act_crop.isEnabled()
    window.handle_escape()


def test_crop_from_a_drag_changes_the_dimensions(qtbot, tmp_path, settings):
    source = tmp_path / "photo.png"
    make_photo(source)
    window = make_window(qtbot, settings)
    window.open_path(source)
    window.canvas.set_tool("rect")

    qtbot.mousePress(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(280, 195))
    qtbot.mouseMove(window.canvas, QPoint(325, 232))
    qtbot.mouseRelease(window.canvas, Qt.MouseButton.LeftButton, pos=QPoint(325, 232))
    window.crop()

    assert window.doc.width < 80
    assert window.doc.height < 60
    window.undo()
    assert window.doc.width == 80


def test_slideshow_stops_at_the_end_when_not_looping(qtbot, tmp_path, settings):
    first = tmp_path / "a.png"
    second = tmp_path / "b.png"
    make_photo(first, 40, 30)
    make_photo(second, 40, 30)
    settings.set("navigation.slideshow_loop", False)
    settings.set("navigation.slideshow_interval", 1)
    window = make_window(qtbot, settings)
    window.open_path(first)

    window.act_slideshow.trigger()
    assert window.act_slideshow.isChecked()
    assert window._slideshow_timer.isActive()

    window._slideshow_tick()
    assert window.doc.path.name == "b.png"

    window._slideshow_tick()
    assert not window._slideshow_timer.isActive()
    assert not window.act_slideshow.isChecked()
    assert window.doc.path.name == "b.png"


def test_help_and_about_windows_can_be_constructed(qtbot, settings):
    from lumen.dialogs import AboutDialog, HelpDialog

    window = make_window(qtbot, settings)
    help_dialog = HelpDialog(window)
    qtbot.addWidget(help_dialog)
    help_dialog.show()
    assert help_dialog.isVisible()

    about = AboutDialog(window)
    qtbot.addWidget(about)
    about.show()
    assert about.isVisible()
