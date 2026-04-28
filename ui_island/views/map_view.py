"""Interactive local map panel with pan/zoom support."""
from __future__ import annotations

import math

import cv2
import numpy as np
from PySide6.QtCore import QPoint, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QImage, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QWidget

from base import TrackState
from route_manager import NODE_TYPE_COLLECT, NODE_TYPE_TELEPORT, NODE_TYPE_VIRTUAL, RouteManager

from ..design import strings
from ..widgets.context_menu import ContextMenuItem, show_context_menu

_HIT_RADIUS_WIDGET_PX = 8


class MapView(QWidget):
    """Interactive crop of the big map with player marker and routes."""

    relocate_requested = Signal(int, int)
    manual_view_changed = Signal()
    add_point_requested = Signal(int, int)
    add_annotation_requested = Signal(int, int)
    delete_point_requested = Signal(str, int)
    mark_point_visited_requested = Signal(str, int, bool)
    change_point_annotation_requested = Signal(str, int)
    delete_point_annotation_requested = Signal(str, int)
    change_point_node_type_requested = Signal(str, int, object)
    change_annotation_requested = Signal(str, int)
    add_annotation_to_route_requested = Signal(str, int)
    delete_annotation_requested = Signal(str, int)
    guide_hint_changed = Signal(object)
    drawing_point_requested = Signal(int, int)
    drawing_undo_requested = Signal()

    _ABSOLUTE_MIN_ZOOM = 0.05
    _MAX_ZOOM = 3.5
    _ZOOM_STEP = 1.18

    def __init__(self, route_mgr: RouteManager, parent=None) -> None:
        super().__init__(parent)
        self.route_mgr = route_mgr
        self._pixmap: QPixmap | None = None
        self._base_map: np.ndarray | None = None
        self._map_w = 0
        self._map_h = 0
        self._last_vx1 = 0
        self._last_vy1 = 0
        self._last_crop_size = (0, 0)
        self._last_draw_rect = QRectF()
        self._zoom = 1.0
        self._center_locked = True
        self._view_center: QPointF | None = None
        self._drag_last_pos: QPointF | None = None
        self._left_press_pos: QPointF | None = None
        self._left_press_map: tuple[float, float] | None = None
        self._left_dragging = False
        self._hover_map_pos: tuple[float, float] | None = None
        self._drawing_context: dict | None = None
        self._last_player: tuple[int, int] | None = None
        self._last_state: TrackState | None = None
        self._last_auto_visit = True
        self._last_minimap: np.ndarray | None = None
        self._ARROW_HALF = 16   # 从小地图中心裁取 ±16px 的箭头区域
        self._arrow_alpha = self._build_arrow_alpha(self._ARROW_HALF)
        self.setMinimumSize(260, 180)
        self.setAttribute(Qt.WA_OpaquePaintEvent, False)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)

    def set_map(self, base_map_bgr: np.ndarray) -> None:
        self._base_map = base_map_bgr
        self._map_h, self._map_w = base_map_bgr.shape[:2]

    def set_center_locked(self, locked: bool) -> None:
        self._center_locked = locked
        if locked and self._last_player is not None:
            self._view_center = QPointF(float(self._last_player[0]), float(self._last_player[1]))
            self._refresh_from_last_frame()

    def reset_view(self) -> None:
        self._zoom = 1.0
        self.set_center_locked(True)
        self._refresh_from_last_frame()

    def preview_relocate(self, x: int, y: int, state: TrackState, auto_visit: bool = False) -> None:
        self._last_player = (x, y)
        self._last_state = state
        self._last_auto_visit = bool(auto_visit)
        self._zoom = max(self._zoom, self._min_zoom_for_full_map())
        self._center_locked = True
        self._view_center = QPointF(float(x), float(y))
        self._render_frame(state, x, y, auto_visit=auto_visit)

    def focus_map_position(self, x: int, y: int) -> None:
        self._center_locked = False
        self._view_center = QPointF(float(x), float(y))
        self._refresh_from_last_frame()

    def update_frame(
        self,
        state: TrackState,
        cx: int | None,
        cy: int | None,
        minimap_bgr: np.ndarray | None = None,
    ) -> None:
        if self._base_map is None or cx is None or cy is None:
            return

        self._last_state = state
        self._last_player = (cx, cy)
        self._last_auto_visit = True
        if minimap_bgr is not None:
            self._last_minimap = minimap_bgr
        if self._center_locked or self._view_center is None:
            self._view_center = QPointF(float(cx), float(cy))

        self._render_frame(state, cx, cy, auto_visit=True)

    def _render_frame(self, state: TrackState, cx: int, cy: int, auto_visit: bool = True) -> None:
        if self._base_map is None or self._view_center is None:
            return

        crop_w, crop_h = self._crop_dimensions()
        vx1, vy1, vx2, vy2 = self._crop_bounds(crop_w, crop_h)
        crop = self._base_map[vy1:vy2, vx1:vx2].copy()

        self._last_vx1, self._last_vy1 = vx1, vy1
        self._last_crop_size = (crop.shape[1], crop.shape[0])

        drawing_route = self._drawing_route_payload()
        drawing_active = drawing_route is not None
        draw_player_x = None if drawing_active else cx
        draw_player_y = None if drawing_active else cy
        self.route_mgr.draw_on(
            crop,
            vx1,
            vy1,
            max(crop_w, crop_h),
            draw_player_x,
            draw_player_y,
            drawing_route=drawing_route,
            auto_visit=auto_visit,
        )
        if drawing_active:
            self.guide_hint_changed.emit(None)
        else:
            self.guide_hint_changed.emit(
                self.route_mgr.guide_hint_for_view(cx, cy, vx1, vy1, crop.shape[1], crop.shape[0])
            )

        local_x = cx - vx1
        local_y = cy - vy1
        if not drawing_active and 0 <= local_x < crop.shape[1] and 0 <= local_y < crop.shape[0]:
            if state == TrackState.INERTIAL:
                # 惯性态无新截图：黄圈降级显示
                cv2.circle(crop, (local_x, local_y), 10, (0, 255, 255), -1)
                cv2.circle(crop, (local_x, local_y), 12, (0, 150, 150), 2)
            else:
                # 精确锁定 / 搜索态：贴游戏原生箭头
                self._paste_minimap_arrow(crop, local_x, local_y)

        rgb = cv2.cvtColor(crop, cv2.COLOR_BGR2RGB)
        height, width, _ = rgb.shape
        image = QImage(rgb.data, width, height, width * 3, QImage.Format_RGB888).copy()
        self._pixmap = QPixmap.fromImage(image)
        self.update()

    def _crop_dimensions(self) -> tuple[int, int]:
        view_w = max(self.width(), 100)
        view_h = max(self.height(), 100)
        self._zoom = min(self._MAX_ZOOM, max(self._min_zoom_for_full_map(), self._zoom))
        crop_w = max(120, int(view_w / self._zoom))
        crop_h = max(120, int(view_h / self._zoom))
        return crop_w, crop_h

    def _min_zoom_for_full_map(self) -> float:
        if self._map_w <= 0 or self._map_h <= 0:
            return self._ABSOLUTE_MIN_ZOOM
        view_w = max(self.width(), 100)
        view_h = max(self.height(), 100)
        return max(
            self._ABSOLUTE_MIN_ZOOM,
            min(view_w / self._map_w, view_h / self._map_h),
        )

    def _crop_bounds(self, crop_w: int, crop_h: int) -> tuple[int, int, int, int]:
        assert self._view_center is not None

        center_x = self._view_center.x()
        center_y = self._view_center.y()
        half_w = crop_w / 2.0
        half_h = crop_h / 2.0

        max_vx1 = max(0, self._map_w - crop_w)
        max_vy1 = max(0, self._map_h - crop_h)
        vx1 = int(round(min(max(center_x - half_w, 0), max_vx1)))
        vy1 = int(round(min(max(center_y - half_h, 0), max_vy1)))
        vx2 = min(self._map_w, vx1 + crop_w)
        vy2 = min(self._map_h, vy1 + crop_h)

        self._view_center = QPointF(vx1 + (vx2 - vx1) / 2.0, vy1 + (vy2 - vy1) / 2.0)
        return vx1, vy1, vx2, vy2

    def _paste_minimap_arrow(self, crop: np.ndarray, local_x: int, local_y: int) -> None:
        """用径向正弦 alpha 遮罩把游戏小地图中央箭头贴到玩家位置，消除矩形硬边。"""
        half = self._ARROW_HALF
        if self._last_minimap is not None:
            mini = self._last_minimap
            mh, mw = mini.shape[:2]
            my1, my2 = mh // 2 - half, mh // 2 + half
            mx1, mx2 = mw // 2 - half, mw // 2 + half
            if my1 >= 0 and mx1 >= 0 and my2 <= mh and mx2 <= mw:
                arrow = mini[my1:my2, mx1:mx2]
                ay1, ax1 = local_y - half, local_x - half
                ay2, ax2 = ay1 + 2 * half, ax1 + 2 * half
                if ay1 >= 0 and ax1 >= 0 and ay2 <= crop.shape[0] and ax2 <= crop.shape[1]:
                    roi = crop[ay1:ay2, ax1:ax2]
                    alpha = self._arrow_alpha
                    blended = arrow.astype(np.float32) * alpha + roi.astype(np.float32) * (1.0 - alpha)
                    crop[ay1:ay2, ax1:ax2] = np.clip(blended, 0, 255).astype(np.uint8)
                    return
        # 降级：小地图不可用时画红圈
        cv2.circle(crop, (local_x, local_y), 8, (0, 0, 255), -1)
        cv2.circle(crop, (local_x, local_y), 10, (255, 255, 255), 2)

    @staticmethod
    def _build_arrow_alpha(half: int) -> np.ndarray:
        """(2*half, 2*half, 1) float32：内 55% 全覆盖，外圈 sin² 柔化到 0。"""
        size = 2 * half
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32)
        cx = cy = half - 0.5
        dist = np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2)
        inner = half * 0.55
        t = np.clip((half - dist) / max(half - inner, 1e-6), 0.0, 1.0)
        alpha = np.where(dist <= inner, 1.0, np.sin(t * np.pi / 2.0) ** 2)
        return alpha.astype(np.float32)[..., None]

    def _refresh_from_last_frame(self) -> None:
        if self._last_state is None or self._last_player is None:
            return
        self._render_frame(
            self._last_state,
            self._last_player[0],
            self._last_player[1],
            auto_visit=self._last_auto_visit,
        )

    def _draw_rect(self) -> QRectF:
        if self._pixmap is None:
            return QRectF()
        scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (self.width() - scaled.width()) / 2.0
        y = (self.height() - scaled.height()) / 2.0
        return QRectF(x, y, float(scaled.width()), float(scaled.height()))

    def _widget_to_map(self, pos: QPointF) -> tuple[float, float] | None:
        if self._pixmap is None:
            return None
        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        if not draw_rect.contains(pos):
            return None

        crop_w, crop_h = self._last_crop_size
        if crop_w <= 0 or crop_h <= 0:
            return None

        rel_x = (pos.x() - draw_rect.left()) / draw_rect.width()
        rel_y = (pos.y() - draw_rect.top()) / draw_rect.height()
        map_x = self._last_vx1 + rel_x * crop_w
        map_y = self._last_vy1 + rel_y * crop_h
        return map_x, map_y

    def _map_to_widget(self, map_x: float, map_y: float) -> QPointF | None:
        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        crop_w, crop_h = self._last_crop_size
        if draw_rect.width() <= 0 or draw_rect.height() <= 0 or crop_w <= 0 or crop_h <= 0:
            return None
        rel_x = (map_x - self._last_vx1) / crop_w
        rel_y = (map_y - self._last_vy1) / crop_h
        return QPointF(
            draw_rect.left() + rel_x * draw_rect.width(),
            draw_rect.top() + rel_y * draw_rect.height(),
        )

    def set_route_drawing_context(self, context: dict | None) -> None:
        self._drawing_context = dict(context) if isinstance(context, dict) else None
        self._refresh_from_last_frame()

    def _is_drawing_active(self) -> bool:
        return bool(isinstance(self._drawing_context, dict) and self._drawing_context.get("active"))

    def _is_drawing_paused(self) -> bool:
        return bool(self._is_drawing_active() and self._drawing_context and self._drawing_context.get("paused"))

    def _drawing_route_payload(self) -> dict | None:
        if not self._is_drawing_active() or not self._drawing_context:
            return None
        return {
            "id": self._drawing_context.get("route_id", ""),
            "display_name": self._drawing_context.get("name", ""),
            "points": self._drawing_context.get("points") or [],
            "loop": bool(self._drawing_context.get("loop")),
            "_hide_other_routes": bool(self._drawing_context.get("hide_other_routes")),
        }

    def _draw_drawing_preview(self, painter: QPainter) -> None:
        if not self._is_drawing_active() or self._is_drawing_paused() or not self._drawing_context:
            return
        points = self._drawing_context.get("points") or []
        if not points or self._hover_map_pos is None:
            return
        last = points[-1]
        if not isinstance(last, dict):
            return
        try:
            start = self._map_to_widget(float(last["x"]), float(last["y"]))
        except (KeyError, TypeError, ValueError):
            return
        end = self._map_to_widget(self._hover_map_pos[0], self._hover_map_pos[1])
        if start is None or end is None:
            return
        node_type = str(self._drawing_context.get("node_type") or NODE_TYPE_COLLECT)
        pen = QPen(QColor(255, 255, 255), 2)
        if node_type == NODE_TYPE_TELEPORT:
            pen.setStyle(Qt.DashLine)
        elif node_type == NODE_TYPE_VIRTUAL:
            pen.setStyle(Qt.DotLine)
        painter.setPen(pen)
        painter.drawLine(start, end)

    def _disable_center_lock(self) -> None:
        if not self._center_locked:
            return
        self._center_locked = False
        self.manual_view_changed.emit()

    def paintEvent(self, _event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.SmoothPixmapTransform)
        if self._pixmap is None:
            self._last_draw_rect = QRectF()
            return

        scaled = self._pixmap.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        x = (self.width() - scaled.width()) / 2.0
        y = (self.height() - scaled.height()) / 2.0
        self._last_draw_rect = QRectF(x, y, float(scaled.width()), float(scaled.height()))
        painter.drawPixmap(int(x), int(y), scaled)
        self._draw_drawing_preview(painter)

    def resizeEvent(self, event):
        super().resizeEvent(event)

    def keyPressEvent(self, event):
        if (
            self._is_drawing_active()
            and event.key() == Qt.Key_Z
            and event.modifiers() & Qt.ControlModifier
        ):
            self.drawing_undo_requested.emit()
            event.accept()
            return
        super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton and self._pixmap is not None:
            self.setFocus(Qt.MouseFocusReason)
            self._left_press_pos = event.position()
            self._left_press_map = self._widget_to_map(event.position())
            self._left_dragging = False
            self._drag_last_pos = event.position()
            event.accept()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        self._hover_map_pos = self._widget_to_map(event.position())
        if self._is_drawing_active() and not self._is_drawing_paused():
            self.update()

        if self._drag_last_pos is None or self._view_center is None:
            super().mouseMoveEvent(event)
            return

        if self._left_press_pos is not None and not self._left_dragging:
            delta_from_press = event.position() - self._left_press_pos
            app = QApplication.instance()
            threshold = app.startDragDistance() if app is not None else QApplication.startDragDistance()
            threshold = max(1, int(threshold))
            if max(abs(delta_from_press.x()), abs(delta_from_press.y())) < threshold:
                event.accept()
                return
            self._left_dragging = True

        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        crop_w, crop_h = self._last_crop_size
        if draw_rect.width() <= 0 or draw_rect.height() <= 0 or crop_w <= 0 or crop_h <= 0:
            super().mouseMoveEvent(event)
            return

        delta = event.position() - self._drag_last_pos
        ratio_x = crop_w / draw_rect.width()
        ratio_y = crop_h / draw_rect.height()
        self._view_center = QPointF(
            self._view_center.x() - delta.x() * ratio_x,
            self._view_center.y() - delta.y() * ratio_y,
        )
        self._drag_last_pos = event.position()
        self._disable_center_lock()
        self._refresh_from_last_frame()
        event.accept()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.LeftButton:
            mapped = self._widget_to_map(event.position())
            should_add = (
                self._is_drawing_active()
                and not self._is_drawing_paused()
                and not self._left_dragging
                and mapped is not None
                and self._left_press_map is not None
            )
            self._drag_last_pos = None
            self._left_press_pos = None
            self._left_press_map = None
            self._left_dragging = False
            if should_add:
                self.drawing_point_requested.emit(int(mapped[0]), int(mapped[1]))
                event.accept()
                return
        self._drag_last_pos = None
        super().mouseReleaseEvent(event)

    def wheelEvent(self, event):
        if self._pixmap is None:
            super().wheelEvent(event)
            return

        anchor_map = self._widget_to_map(event.position())
        old_zoom = self._zoom
        if event.angleDelta().y() > 0:
            self._zoom = min(self._MAX_ZOOM, self._zoom * self._ZOOM_STEP)
        else:
            self._zoom = max(self._min_zoom_for_full_map(), self._zoom / self._ZOOM_STEP)

        if math.isclose(self._zoom, old_zoom):
            return

        if anchor_map is not None:
            crop_w = max(120, int(max(self.width(), 100) / self._zoom))
            crop_h = max(120, int(max(self.height(), 100) / self._zoom))
            draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
            if draw_rect.width() > 0 and draw_rect.height() > 0:
                rel_x = (event.position().x() - draw_rect.left()) / draw_rect.width()
                rel_y = (event.position().y() - draw_rect.top()) / draw_rect.height()
                self._view_center = QPointF(
                    anchor_map[0] - (rel_x - 0.5) * crop_w,
                    anchor_map[1] - (rel_y - 0.5) * crop_h,
                )

        self._disable_center_lock()
        self._refresh_from_last_frame()
        event.accept()

    def mouseDoubleClickEvent(self, event):
        if self._is_drawing_active():
            event.accept()
            return
        mapped = self._widget_to_map(event.position())
        if mapped is None:
            return
        self.relocate_requested.emit(int(mapped[0]), int(mapped[1]))

    def _hit_test_node(self, widget_pos: QPointF) -> tuple[str, int] | None:
        mapped = self._widget_to_map(widget_pos)
        if mapped is None:
            return None
        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        if draw_rect.width() <= 0 or self._last_crop_size[0] <= 0:
            return None
        ratio = self._last_crop_size[0] / draw_rect.width()
        map_threshold = max(6.0, _HIT_RADIUS_WIDGET_PX * ratio)
        return self.route_mgr.hit_test_point(mapped[0], mapped[1], map_threshold)

    def _hit_test_draft_node(self, widget_pos: QPointF) -> int | None:
        mapped = self._widget_to_map(widget_pos)
        context = self._drawing_context if isinstance(self._drawing_context, dict) else None
        if mapped is None or not context:
            return None
        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        if draw_rect.width() <= 0 or self._last_crop_size[0] <= 0:
            return None
        ratio = self._last_crop_size[0] / draw_rect.width()
        map_threshold = max(6.0, _HIT_RADIUS_WIDGET_PX * ratio)
        best: tuple[float, int] | None = None
        for index, point in enumerate(context.get("points") or []):
            if not isinstance(point, dict):
                continue
            try:
                px = float(point["x"])
                py = float(point["y"])
            except (KeyError, TypeError, ValueError):
                continue
            dist = math.hypot(px - mapped[0], py - mapped[1])
            if dist > map_threshold:
                continue
            if best is None or dist < best[0]:
                best = (dist, index)
        return None if best is None else best[1]

    def _hit_test_annotation(self, widget_pos: QPointF) -> dict | None:
        mapped = self._widget_to_map(widget_pos)
        if mapped is None:
            return None
        draw_rect = self._last_draw_rect if not self._last_draw_rect.isNull() else self._draw_rect()
        if draw_rect.width() <= 0 or self._last_crop_size[0] <= 0:
            return None
        ratio = self._last_crop_size[0] / draw_rect.width()
        map_threshold = max(6.0, _HIT_RADIUS_WIDGET_PX * ratio)
        return self.route_mgr.hit_test_annotation_point(mapped[0], mapped[1], map_threshold)

    def contextMenuEvent(self, event):
        pos = QPointF(event.pos())
        if self._is_drawing_active():
            draft_hit = self._hit_test_draft_node(pos)
            if draft_hit is not None:
                route_id = str(self._drawing_context.get("route_id") or "") if self._drawing_context else ""
                point = (self._drawing_context.get("points") or [])[draft_hit] if self._drawing_context else {}
                has_annotation = bool(
                    isinstance(point, dict)
                    and (str(point.get("typeId") or "").strip() or str(point.get("type") or "").strip())
                )
                annotation_label = (
                    strings.CHANGE_POINT_ANNOTATION_MENU_LABEL
                    if has_annotation
                    else strings.ADD_POINT_ANNOTATION_MENU_LABEL
                )
                items = [
                    ContextMenuItem(
                        annotation_label,
                        lambda rid=route_id, idx=draft_hit: self.change_point_annotation_requested.emit(rid, idx),
                    ),
                    ContextMenuItem(
                        strings.CHANGE_POINT_NODE_TYPE_MENU_LABEL,
                        lambda rid=route_id, idx=draft_hit, gpos=QPoint(event.globalPos()):
                        self.change_point_node_type_requested.emit(rid, idx, gpos),
                    ),
                ]
                if has_annotation:
                    items.append(
                        ContextMenuItem(
                            strings.DELETE_POINT_ANNOTATION_MENU_LABEL,
                            lambda rid=route_id, idx=draft_hit:
                            self.delete_point_annotation_requested.emit(rid, idx),
                        )
                    )
                items.extend(
                    [
                        ContextMenuItem.separator_item(),
                        ContextMenuItem(
                            strings.DELETE_POINT_MENU_LABEL,
                            lambda rid=route_id, idx=draft_hit: self.delete_point_requested.emit(rid, idx),
                        ),
                    ]
                )
                show_context_menu(
                    self,
                    event.globalPos(),
                    items,
                    object_name="MapNodeContextMenu",
                )
                event.accept()
                return

        hit = self._hit_test_node(pos)
        if hit is not None:
            route_id, point_index = hit
            visited = self.route_mgr.point_visited(route_id, point_index)
            has_annotation = self.route_mgr.route_point_has_annotation(route_id, point_index)
            annotation_label = (
                strings.CHANGE_POINT_ANNOTATION_MENU_LABEL
                if has_annotation
                else strings.ADD_POINT_ANNOTATION_MENU_LABEL
            )
            items = [
                ContextMenuItem(
                    strings.MARK_POINT_UNVISITED_MENU_LABEL if visited else strings.MARK_POINT_VISITED_MENU_LABEL,
                    lambda rid=route_id, idx=point_index, state=not bool(visited):
                    self.mark_point_visited_requested.emit(rid, idx, state),
                ),
                ContextMenuItem(
                    annotation_label,
                    lambda rid=route_id, idx=point_index: self.change_point_annotation_requested.emit(rid, idx),
                ),
                ContextMenuItem(
                    strings.CHANGE_POINT_NODE_TYPE_MENU_LABEL,
                    lambda rid=route_id, idx=point_index, gpos=QPoint(event.globalPos()):
                    self.change_point_node_type_requested.emit(rid, idx, gpos),
                ),
            ]
            if has_annotation:
                items.append(
                    ContextMenuItem(
                        strings.DELETE_POINT_ANNOTATION_MENU_LABEL,
                        lambda rid=route_id, idx=point_index:
                        self.delete_point_annotation_requested.emit(rid, idx),
                    )
                )
            items.extend(
                [
                    ContextMenuItem.separator_item(),
                    ContextMenuItem(
                        strings.DELETE_POINT_MENU_LABEL,
                        lambda rid=route_id, idx=point_index: self.delete_point_requested.emit(rid, idx),
                    ),
                ]
            )
            show_context_menu(self, event.globalPos(), items, object_name="MapNodeContextMenu")
            event.accept()
            return

        annotation_hit = self._hit_test_annotation(pos)
        if annotation_hit is not None:
            type_id = str(annotation_hit.get("typeId") or "")
            point_index = int(annotation_hit.get("pointIndex"))
            show_context_menu(
                self,
                event.globalPos(),
                [
                    ContextMenuItem(
                        strings.MAP_CHANGE_ANNOTATION_MENU_LABEL,
                        lambda tid=type_id, idx=point_index: self.change_annotation_requested.emit(tid, idx),
                    ),
                    ContextMenuItem(
                        strings.MAP_ADD_ANNOTATION_TO_ROUTE_MENU_LABEL,
                        lambda tid=type_id, idx=point_index:
                        self.add_annotation_to_route_requested.emit(tid, idx),
                    ),
                    ContextMenuItem.separator_item(),
                    ContextMenuItem(
                        strings.MAP_DELETE_ANNOTATION_MENU_LABEL,
                        lambda tid=type_id, idx=point_index: self.delete_annotation_requested.emit(tid, idx),
                    ),
                ],
                object_name="MapAnnotationContextMenu",
            )
            event.accept()
            return

        mapped = self._widget_to_map(pos)
        if mapped is None:
            event.ignore()
            return
        map_x = int(mapped[0])
        map_y = int(mapped[1])
        show_context_menu(
            self,
            event.globalPos(),
            [
                ContextMenuItem(
                    strings.MAP_ADD_ANNOTATION_MENU_LABEL,
                    lambda x=map_x, y=map_y: self.add_annotation_requested.emit(x, y),
                ),
                ContextMenuItem(
                    strings.MAP_ADD_POINT_MENU_LABEL,
                    lambda x=map_x, y=map_y: self.add_point_requested.emit(x, y),
                ),
            ],
            object_name="MapBlankContextMenu",
        )
        event.accept()
