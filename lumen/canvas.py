"""The image canvas: zoom, pan, marching ants, selection tools, floating layer."""

from __future__ import annotations

import math

from PySide6.QtCore import QEvent, QPoint, QPointF, QRectF, QSizeF, Qt, QTimer, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QImage,
    QMovie,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QWidget

MIN_ZOOM = 0.02
MAX_ZOOM = 32.0
FIT_PADDING = 24
ANTS_INTERVAL_MS = 90


class Canvas(QWidget):
    advance = Signal(int)
    zoom_changed = Signal(float, bool)
    tool_changed = Signal(str)
    escape_pressed = Signal()
    cursor_moved = Signal(QPoint)

    def __init__(self, document, settings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.document = document
        self.settings = settings
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, True)

        self._zoom = 1.0
        self._fit = True
        self._pan = QPointF(0.0, 0.0)
        self._tool = "none"
        self._movie: QMovie | None = None
        self._movie_frames = 0
        self._dark = True
        self._smooth = True

        self._mode: str | None = None  # select | move | pan | click
        self._anchor = QPointF()
        self._drag_end = QPointF()
        self._points: list[QPointF] = []
        self._last_image_point = QPointF()
        self._press_pos = QPointF()
        self._moved = False
        self._pan_origin = QPointF()
        self._last_modifiers = Qt.KeyboardModifier.NoModifier

        self._checker_brushes: dict[bool, QBrush] = {}
        self._ants_offset = 0.0
        self._ants_timer = QTimer(self)
        self._ants_timer.setInterval(ANTS_INTERVAL_MS)
        self._ants_timer.timeout.connect(self._tick_ants)

        self._wheel_accum = 0

        document.image_changed.connect(self.update)
        document.selection_changed.connect(self._selection_changed)
        self._selection_changed()
        self._configure_from_settings()

    # -- settings ---------------------------------------------------------
    def _configure_from_settings(self) -> None:
        self._smooth = self.settings.get("appearance.scaling", "smooth") == "smooth"
        self.update()

    def settings_changed(self, key: str) -> None:
        if not key or key.startswith("appearance"):
            self._configure_from_settings()
        if not key or key.startswith("navigation"):
            self._update_cursor()

    def set_dark(self, dark: bool) -> None:
        self._dark = dark
        self.update()

    # -- document lifecycle -----------------------------------------------
    def reset_view(self) -> None:
        self.fit_to_window()

    def set_movie(self, movie: QMovie | None) -> None:
        if self._movie is not None and self._movie is not movie:
            self._movie.stop()
            for signal, slot in (
                (self._movie.frameChanged, self._on_movie_frame),
                (self._movie.finished, self._on_movie_finished),
                (self._movie.updated, self.update),
            ):
                try:
                    signal.disconnect(slot)
                except (RuntimeError, TypeError):
                    pass
            self._movie.deleteLater()
        self._movie = movie
        self._movie_frames = 0
        if movie is not None:
            movie.setCacheMode(QMovie.CacheMode.CacheNone)
            movie.frameChanged.connect(self._on_movie_frame)
            movie.finished.connect(self._on_movie_finished)
            movie.updated.connect(self.update)
            if self.settings.get("navigation.animation_autoplay", True):
                movie.start()
        self.update()

    def _on_movie_frame(self, frame: int) -> None:
        looping = bool(self.settings.get("navigation.animation_loop", True))
        if frame == 0 and self._movie_frames > 0 and not looping:
            if self._movie is not None:
                self._movie.stop()
            return
        self._movie_frames += 1

    def _on_movie_finished(self) -> None:
        if (
            self.settings.get("navigation.animation_loop", True)
            and self._movie is not None
        ):
            self._movie_frames = 0
            self._movie.start()

    def toggle_animation(self) -> None:
        if self._movie is None:
            return
        if self._movie.state() == QMovie.MovieState.Running:
            self._movie.setPaused(True)
        else:
            self._movie_frames = 0
            self._movie.start()

    @property
    def has_animation(self) -> bool:
        return self._movie is not None

    # -- geometry ---------------------------------------------------------
    def _image_size(self) -> QSizeF:
        if not self.document.has_image:
            return QSizeF(0, 0)
        return QSizeF(self.document.width, self.document.height)

    def _image_rect(self) -> QRectF:
        size = self._image_size()
        displayed = QSizeF(size.width() * self._zoom, size.height() * self._zoom)
        center = QPointF(self.rect().center())
        origin = (
            center - QPointF(displayed.width() / 2, displayed.height() / 2) + self._pan
        )
        return QRectF(origin, displayed)

    def _widget_to_image(self, pos: QPointF) -> QPointF:
        origin = self._image_rect().topLeft()
        return (pos - origin) / self._zoom

    def _image_to_widget(self, point: QPointF) -> QPointF:
        origin = self._image_rect().topLeft()
        return origin + point * self._zoom

    def _clamp_to_image(self, point: QPointF) -> QPointF:
        size = self._image_size()
        return QPointF(
            min(max(point.x(), 0.0), max(size.width(), 0.0)),
            min(max(point.y(), 0.0), max(size.height(), 0.0)),
        )

    def _fits(self) -> bool:
        return self._fit

    def _pans(self) -> bool:
        if not self.document.has_image:
            return False
        return self._zoom > self._fit_zoom() + 1e-6

    def _fit_zoom(self) -> float:
        size = self._image_size()
        if size.isEmpty():
            return 1.0
        available_w = max(self.width() - FIT_PADDING * 2, 32)
        available_h = max(self.height() - FIT_PADDING * 2, 32)
        zoom = min(available_w / size.width(), available_h / size.height())
        return max(MIN_ZOOM, min(1.0, zoom))

    def fit_to_window(self) -> None:
        self._fit = True
        self._pan = QPointF(0.0, 0.0)
        if self.document.has_image:
            self._zoom = self._fit_zoom()
        self.update()
        self.zoom_changed.emit(self._zoom, self._fit)

    def actual_size(self) -> None:
        self._fit = False
        self._zoom = 1.0
        self._pan = QPointF(0.0, 0.0)
        self.update()
        self.zoom_changed.emit(self._zoom, self._fit)

    def set_zoom(self, zoom: float) -> None:
        if not self.document.has_image:
            return
        self._zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        self._fit = False
        self.update()
        self.zoom_changed.emit(self._zoom, self._fit)

    def zoom_by(self, factor: float, anchor: QPointF | None = None) -> None:
        if not self.document.has_image:
            return
        new_zoom = max(MIN_ZOOM, min(MAX_ZOOM, self._zoom * factor))
        if abs(new_zoom - self._zoom) < 1e-9:
            return
        if anchor is None:
            anchor = QPointF(self.rect().center())
        before = self._widget_to_image(anchor)
        self._zoom = new_zoom
        self._fit = False
        size = self._image_size()
        displayed = QSizeF(size.width() * new_zoom, size.height() * new_zoom)
        center = QPointF(self.rect().center())
        self._pan = (
            anchor
            - before * new_zoom
            - center
            + QPointF(displayed.width() / 2, displayed.height() / 2)
        )
        self.update()
        self.zoom_changed.emit(self._zoom, self._fit)

    def viewport_center_image(self) -> QPoint:
        center = self._widget_to_image(QPointF(self.rect().center()))
        point = self._clamp_to_image(center)
        return QPoint(int(point.x()), int(point.y()))

    @property
    def zoom(self) -> float:
        return self._zoom

    @property
    def is_fit(self) -> bool:
        return self._fit

    @property
    def tool(self) -> str:
        return self._tool

    def set_tool(self, tool: str) -> None:
        if tool == self._tool:
            return
        self._tool = tool
        self._mode = None
        self._update_cursor()
        if tool != "none":
            self.setFocus(Qt.FocusReason.OtherFocusReason)
        self.tool_changed.emit(tool)

    # -- painting ---------------------------------------------------------
    def resizeEvent(self, event) -> None:
        super().resizeEvent(event)
        if self._fit:
            self._zoom = self._fit_zoom() if self.document.has_image else 1.0
            self.zoom_changed.emit(self._zoom, self._fit)
        self.update()

    def paintEvent(self, event) -> None:
        painter = QPainter(self)
        painter.fillRect(self.rect(), self.palette().window())

        if not self.document.has_image:
            painter.setPen(self.palette().placeholderText().color())
            painter.drawText(
                self.rect(),
                Qt.AlignmentFlag.AlignCenter,
                "Drop an image here\nor press Ctrl+O",
            )
            painter.end()
            return

        rect = self._image_rect()
        self._paint_backdrop(painter, rect)

        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, self._smooth)
        source: QImage | None = None
        if self._movie is not None:
            source = self._movie.currentPixmap().toImage()
            if source.isNull():
                source = self.document.image
        else:
            source = self.document.image
        if source is not None and not source.isNull():
            painter.drawImage(rect, source)

        floating = self.document.floating
        if floating is not None:
            target = self._image_rect_for(floating.rect())
            painter.drawImage(target, floating.image)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, False)

        border = QColor(0, 0, 0, 90) if self._dark else QColor(0, 0, 0, 60)
        painter.setPen(QPen(border, 1))
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.drawRect(rect.adjusted(-0.5, -0.5, 0.5, 0.5))

        self._paint_ants(painter)
        painter.end()

    def _image_rect_for(self, rect) -> QRectF:
        origin = self._image_rect().topLeft()
        return QRectF(
            origin + QPointF(rect.x(), rect.y()) * self._zoom,
            QSizeF(rect.width() * self._zoom, rect.height() * self._zoom),
        )

    def _checker_brush(self) -> QBrush:
        brush = self._checker_brushes.get(self._dark)
        if brush is not None:
            return brush
        first, second = (
            (QColor("#24262a"), QColor("#2e3136"))
            if self._dark
            else (QColor("#e3e3e3"), QColor("#f4f4f4"))
        )
        pixmap = QPixmap(16, 16)
        pixmap.fill(first)
        painter = QPainter(pixmap)
        painter.fillRect(0, 0, 8, 8, second)
        painter.fillRect(8, 8, 8, 8, second)
        painter.end()
        brush = QBrush(pixmap)
        self._checker_brushes[self._dark] = brush
        return brush

    def _paint_backdrop(self, painter: QPainter, rect: QRectF) -> None:
        mode = str(self.settings.get("appearance.backdrop", "checkerboard"))
        painter.save()
        painter.setClipRect(rect)
        if mode == "solid":
            color = QColor(
                str(self.settings.get("appearance.backdrop_color", "#2f3236"))
            )
            painter.fillRect(rect, color)
            painter.restore()
            return
        painter.setBrushOrigin(rect.topLeft().toPoint())
        painter.fillRect(rect, self._checker_brush())
        painter.restore()

    def _paint_ants(self, painter: QPainter) -> None:
        paths: list[QPainterPath] = []
        if self.document.has_selection:
            paths.append(self.document.selection)
        if self.document.floating is not None:
            paths.append(self.document.floating.outline)
        if not paths:
            return

        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        origin = self._image_rect().topLeft()
        painter.translate(origin)
        painter.scale(self._zoom, self._zoom)
        painter.setBrush(Qt.BrushStyle.NoBrush)

        black = QPen(QColor(0, 0, 0), 0)
        black.setStyle(Qt.PenStyle.CustomDashLine)
        black.setDashPattern([4, 4])
        black.setDashOffset(self._ants_offset)
        white = QPen(QColor(255, 255, 255), 0)
        white.setStyle(Qt.PenStyle.CustomDashLine)
        white.setDashPattern([4, 4])
        white.setDashOffset(self._ants_offset + 4)

        for path in paths:
            painter.setPen(black)
            painter.drawPath(path)
            painter.setPen(white)
            painter.drawPath(path)
        painter.restore()

    def _tick_ants(self) -> None:
        self._ants_offset = (self._ants_offset + 1) % 8
        bounds = QRectF()
        if self.document.has_selection:
            bounds = self.document.selection.boundingRect()
        if self.document.floating is not None:
            bounds = bounds.united(self.document.floating.outline.boundingRect())
        if bounds.isEmpty():
            self.update()
            return
        origin = self._image_rect().topLeft()
        target = QRectF(
            origin + bounds.topLeft() * self._zoom,
            QSizeF(bounds.width() * self._zoom, bounds.height() * self._zoom),
        ).adjusted(-4, -4, 4, 4)
        self.update(target.toAlignedRect())

    def _selection_changed(self) -> None:
        active = self.document.has_selection or self.document.floating is not None
        if active and not self._ants_timer.isActive():
            self._ants_timer.start()
        elif not active and self._ants_timer.isActive():
            self._ants_timer.stop()
        self.update()

    # -- mouse ------------------------------------------------------------
    def _update_cursor(self) -> None:
        if self._mode == "pan":
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
            return
        if self._tool != "none":
            self.setCursor(Qt.CursorShape.CrossCursor)
            return
        if self.document.floating is not None:
            self.setCursor(Qt.CursorShape.SizeAllCursor)
            return
        if self._pans():
            self.setCursor(Qt.CursorShape.OpenHandCursor)
            return
        self.setCursor(Qt.CursorShape.ArrowCursor)

    def mousePressEvent(self, event) -> None:
        if not self.document.has_image:
            return
        pos = event.position()
        image_point = self._widget_to_image(pos)
        self._press_pos = pos
        self._moved = False
        self._last_image_point = image_point

        if event.button() == Qt.MouseButton.MiddleButton:
            self._start_pan(pos)
            return

        if event.button() == Qt.MouseButton.RightButton:
            if (
                self.settings.get("navigation.click_to_advance", False)
                and self._tool == "none"
                and self.document.floating is None
            ):
                self.advance.emit(-1)
            return

        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self.document.floating is not None:
            if self.document.floating.outline.contains(image_point):
                self._mode = "move"
                self._update_cursor()
            else:
                self.document.commit_floating()
            return

        if self._tool != "none":
            if self.document.has_selection and self.document.selection_contains(
                image_point.toPoint()
            ):
                if self.document.lift_selection():
                    self._mode = "move"
                    self._last_image_point = image_point
                    self._update_cursor()
                return
            self._mode = "select"
            self._anchor = self._clamp_to_image(image_point)
            self._drag_end = self._anchor
            self._points = [self._anchor]
            self._last_modifiers = event.modifiers()
            self.document.clear_selection()
            return

        if self.document.has_selection:
            self.document.clear_selection()
            return

        if self._pans():
            self._start_pan(pos)
            return

        self._mode = "click"

    def _start_pan(self, pos: QPointF) -> None:
        self._mode = "pan"
        self._press_pos = pos
        self._pan_origin = QPointF(self._pan)
        self._update_cursor()

    def mouseMoveEvent(self, event) -> None:
        pos = event.position()
        image_point = self._widget_to_image(pos)
        point = image_point.toPoint()
        if self.rect().contains(point):
            self.cursor_moved.emit(point)

        if self._mode is None:
            if self.document.floating is not None and self.rect().contains(
                pos.toPoint()
            ):
                if self.document.floating.outline.contains(image_point):
                    self.setCursor(Qt.CursorShape.SizeAllCursor)
                else:
                    self._update_cursor()
            return

        if (pos - self._press_pos).manhattanLength() > 2:
            self._moved = True

        if self._mode == "pan":
            self._pan = self._pan_origin + (pos - self._press_pos)
            self.update()
            return

        if self._mode == "move":
            delta = image_point - self._last_image_point
            step = QPoint(round(delta.x()), round(delta.y()))
            if step.x() or step.y():
                self.document.move_floating(step)
                self._last_image_point += QPointF(step.x(), step.y())
            return

        if self._mode == "select":
            clamped = self._clamp_to_image(image_point)
            if self._tool == "freehand":
                if (
                    not self._points
                    or (clamped - self._points[-1]).manhattanLength() >= 1.5
                ):
                    self._points.append(clamped)
                    self._update_live_selection()
            else:
                self._drag_end = clamped
                self._last_modifiers = event.modifiers()
                self._points = [self._anchor, clamped]
                self._update_live_selection(clamped, event.modifiers())
            return

    def _build_shape(self, end: QPointF, modifiers) -> QPainterPath:
        start = self._anchor
        dx = end.x() - start.x()
        dy = end.y() - start.y()
        path = QPainterPath()
        if modifiers & Qt.KeyboardModifier.AltModifier:
            width = abs(dx) * 2
            height = abs(dy) * 2
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                width = height = max(width, height)
            rect = QRectF(start.x() - width / 2, start.y() - height / 2, width, height)
        else:
            if modifiers & Qt.KeyboardModifier.ShiftModifier:
                side = max(abs(dx), abs(dy))
                dx = math.copysign(side, dx if dx else 1.0)
                dy = math.copysign(side, dy if dy else 1.0)
            rect = QRectF(start, QPointF(start.x() + dx, start.y() + dy)).normalized()
        if self._tool == "ellipse":
            path.addEllipse(rect)
        else:
            path.addRect(rect)
        return path

    def _update_live_selection(
        self, end: QPointF | None = None, modifiers=None
    ) -> None:
        if self._tool == "freehand":
            points = self._points
            if len(points) < 2:
                return
            path = QPainterPath(points[0])
            for i in range(1, len(points) - 1):
                mid = (points[i] + points[i + 1]) / 2
                path.quadTo(points[i], mid)
            path.lineTo(points[-1])
            if len(points) > 3:
                path.closeSubpath()
        else:
            target = end if end is not None else self._drag_end
            mods = modifiers if modifiers is not None else self._last_modifiers
            path = self._build_shape(target, mods)
        self.document.set_selection(path)

    def mouseReleaseEvent(self, event) -> None:
        if event.button() == Qt.MouseButton.MiddleButton and self._mode == "pan":
            self._mode = None
            self._update_cursor()
            return
        if event.button() != Qt.MouseButton.LeftButton:
            return

        mode = self._mode
        self._mode = None

        if mode == "click" and not self._moved:
            if self.settings.get("navigation.click_to_advance", False):
                self.advance.emit(1)
            self._update_cursor()
            return

        if mode == "select":
            if self._tool == "freehand":
                if len(self._points) < 3 or not self._moved:
                    self.document.clear_selection()
                else:
                    self._update_live_selection()
            else:
                if self._moved:
                    self._update_live_selection()
                else:
                    self.document.clear_selection()
        elif mode == "move":
            pass
        self._update_cursor()

    def mouseDoubleClickEvent(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self._tool != "none" or self.document.floating is not None:
            return
        if self._fit:
            self.actual_size()
        else:
            self.fit_to_window()

    def wheelEvent(self, event) -> None:
        if not self.document.has_image:
            return
        ctrl = bool(event.modifiers() & Qt.KeyboardModifier.ControlModifier)
        delta = event.angleDelta().y()
        if delta == 0:
            delta = event.pixelDelta().y() * 8
        mode = str(self.settings.get("navigation.wheel", "navigate"))
        if ctrl or mode == "zoom":
            if delta:
                self.zoom_by(1.0016**delta, event.position())
            event.accept()
            return

        self._wheel_accum += delta
        steps = int(self._wheel_accum / 120)
        if steps:
            self._wheel_accum -= steps * 120
            self.advance.emit(1 if steps > 0 else -1)
        event.accept()

    # -- native gestures ---------------------------------------------------
    def event(self, event):
        if event.type() == QEvent.Type.NativeGesture:
            try:
                if event.gestureType() == Qt.NativeGestureType.ZoomNativeGesture:
                    self.zoom_by(1.0 + event.value(), event.position())
                    return True
            except AttributeError:
                pass
        return super().event(event)

    # -- keys -------------------------------------------------------------
    def keyPressEvent(self, event) -> None:
        if event.key() == Qt.Key.Key_Escape:
            self.escape_pressed.emit()
            return
        if (
            event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter)
            and self.document.floating is not None
        ):
            self.document.commit_floating()
            return
        step = 10 if event.modifiers() & Qt.KeyboardModifier.ShiftModifier else 1
        if event.key() in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            delta = -1 if event.key() == Qt.Key.Key_Left else 1
            if self.document.nudge_floating(delta * step, 0):
                return
            if self.settings.get("navigation.arrow_advance", True):
                self.advance.emit(delta)
            return
        if event.key() in (Qt.Key.Key_Up, Qt.Key.Key_Down):
            delta = -1 if event.key() == Qt.Key.Key_Up else 1
            self.document.nudge_floating(0, delta * step)
            return
        super().keyPressEvent(event)
