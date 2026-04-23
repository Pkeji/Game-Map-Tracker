"""Route panel and route list orchestration."""

from __future__ import annotations

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from ..design import theme
from ..dialogs import toast
from ..dialogs.settings_dialog import styled_confirm
from ..widgets import ElidedCheckBox, RouteListItem, RouteSection, TrackedRouteItem


class RoutePanelController:
    def __init__(self, window) -> None:
        self.window = window
        self.state = window.route_panel_state

    def save_recent_routes(self) -> None:
        self.window.recent_routes_store.save(self.window._recent_route_names)

    def remember_recent_route(self, name: str) -> None:
        recent_route_names = self.window._recent_route_names
        if name in recent_route_names:
            recent_route_names.remove(name)
        recent_route_names.insert(0, name)
        self.save_recent_routes()

    def replace_recent_route_name(self, old_name: str, new_name: str) -> None:
        updated: list[str] = []
        for name in self.window._recent_route_names:
            updated.append(new_name if name == old_name else name)
        self.window._recent_route_names[:] = list(dict.fromkeys(updated))
        self.save_recent_routes()

    def remove_recent_route_name(self, name: str) -> None:
        self.window._recent_route_names[:] = [
            route_name for route_name in self.window._recent_route_names if route_name != name
        ]
        self.save_recent_routes()

    @staticmethod
    def matches_route(route_name: str, term: str) -> bool:
        return not term or term in route_name.casefold()

    def build_add_category_row(self) -> None:
        add_category_row = QFrame()
        add_category_row.setObjectName("PanelCard")
        add_category_row.hide()

        row_layout = QHBoxLayout(add_category_row)
        row_layout.setContentsMargins(8, 8, 8, 8)
        row_layout.setSpacing(6)

        add_category_input = QLineEdit()
        add_category_input.setPlaceholderText("输入类别名称...")
        add_category_input.returnPressed.connect(self.confirm_add_category)
        add_category_input.editingFinished.connect(self.queue_cancel_add_category_if_needed)
        row_layout.addWidget(add_category_input, stretch=1)

        add_category_confirm_btn = QPushButton("✓")
        add_category_confirm_btn.setObjectName("HeaderWindowButton")
        add_category_confirm_btn.setProperty("iconRole", "confirm")
        add_category_confirm_btn.setToolTip("确认创建类别")
        add_category_confirm_btn.setFixedWidth(30)
        add_category_confirm_btn.clicked.connect(self.confirm_add_category)
        row_layout.addWidget(add_category_confirm_btn)

        add_category_cancel_btn = QPushButton("×")
        add_category_cancel_btn.setObjectName("HeaderWindowButton")
        add_category_cancel_btn.setProperty("iconRole", "close")
        add_category_cancel_btn.setToolTip("取消新增类别")
        add_category_cancel_btn.setFixedWidth(30)
        add_category_cancel_btn.clicked.connect(self.cancel_add_category)
        row_layout.addWidget(add_category_cancel_btn)

        self.window._add_category_row = add_category_row
        self.window._add_category_input = add_category_input
        self.window._add_category_confirm_btn = add_category_confirm_btn
        self.window._add_category_cancel_btn = add_category_cancel_btn

    def build_route_sections(self) -> None:
        for category in self.window.route_mgr.categories:
            section = RouteSection(category)
            self.window._route_sections[category] = section
            self.window._route_widgets_by_category[category] = []

            routes = sorted(
                self.window.route_mgr.route_groups[category],
                key=lambda route: route.get("display_name", ""),
            )
            for route in routes:
                name = route.get("display_name", "")
                route_item = self.create_route_list_item(category, name)
                section.add_widget(route_item)
                self.window._route_widgets_by_category[category].append((name, route_item))

            self.window.routes_layout.addWidget(section)

    def clear_route_sections(self) -> None:
        for route_widgets in self.window._route_widgets_by_category.values():
            for name, route_item in route_widgets:
                self.unregister_route_checkbox(name, route_item.checkbox)

        while self.window.routes_layout.count():
            item = self.window.routes_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                if widget is self.window._add_category_row:
                    widget.hide()
                    continue
                if widget is self.window._active_route_rename_item:
                    self.window._active_route_rename_item = None
                widget.deleteLater()

        self.window._route_sections.clear()
        self.window._route_widgets_by_category.clear()

    def rebuild_route_sections(self) -> None:
        self.clear_route_sections()
        if self.window._add_category_row is not None:
            self.window.routes_layout.addWidget(self.window._add_category_row)
        self.build_route_sections()
        self.window.routes_layout.addStretch()
        self.window.routes_scroll_inner.adjustSize()
        self.window.interaction_controller.install_resize_filters(self.window.routes_scroll_inner)

    def reload_route_list(self) -> None:
        self.cancel_active_route_rename()
        self.window.route_mgr.reload()
        known_routes = {
            route.get("display_name")
            for routes in self.window.route_mgr.route_groups.values()
            for route in routes
        }
        self.window._recent_route_names[:] = [name for name in self.window._recent_route_names if name in known_routes]
        self.save_recent_routes()
        self.rebuild_route_sections()
        self.refresh_tracked_routes()
        self.apply_route_filter()
        self.window.map_view._refresh_from_last_frame()
        self.window.window_mode_controller.schedule_layout_refresh()

    def create_route_list_item(self, category: str, name: str) -> RouteListItem:
        route_item = RouteListItem(category, name, self.window.route_mgr.visibility.get(name, False))
        route_item.checkbox.toggled.connect(
            lambda enabled, route_name=name, source=route_item.checkbox: self.toggle_route(route_name, enabled, source)
        )
        route_item.rename_btn.clicked.connect(lambda: self.begin_route_rename(route_item))
        route_item.rename_confirm_btn.clicked.connect(lambda: self.confirm_route_rename(route_item))
        route_item.rename_cancel_btn.clicked.connect(self.cancel_active_route_rename)
        route_item.rename_input.returnPressed.connect(lambda: self.confirm_route_rename(route_item))
        route_item.delete_btn.clicked.connect(
            lambda: self.delete_route(route_item.category, route_item.route_name)
        )
        self.window._route_checkboxes.setdefault(name, []).append(route_item.checkbox)
        return route_item

    def show_add_category_row(self) -> None:
        if self.window._add_category_row is None or self.window._add_category_input is None:
            return
        self.window._adding_category = True
        self.window._add_category_input.clear()
        self.window._add_category_input.setPlaceholderText("输入类别名称...")
        self.window._add_category_row.show()
        self.window._add_category_input.setFocus()
        self.window.window_mode_controller.schedule_layout_refresh()

    def cancel_add_category(self) -> None:
        if self.window._add_category_row is None or self.window._add_category_input is None:
            return
        self.window._adding_category = False
        self.window._add_category_input.clear()
        self.window._add_category_input.setPlaceholderText("输入类别名称...")
        self.window._add_category_row.hide()
        self.window.window_mode_controller.schedule_layout_refresh()

    def confirm_add_category(self) -> None:
        if self.window._add_category_input is None:
            return
        name = self.window._add_category_input.text().strip()
        if not name:
            self.window._add_category_input.clear()
            self.window._add_category_input.setPlaceholderText("类别名称不能为空")
            self.window._add_category_input.setFocus()
            return
        if not self.window.route_mgr.create_category(name):
            self.window._add_category_input.selectAll()
            self.window._add_category_input.setPlaceholderText("名称不能包含 / 或 \\")
            self.window._add_category_input.setFocus()
            return
        self.cancel_add_category()
        self.reload_route_list()

    def queue_cancel_add_category_if_needed(self) -> None:
        QTimer.singleShot(0, self.cancel_add_category_if_focus_left)

    def cancel_add_category_if_focus_left(self) -> None:
        if not self.window._adding_category:
            return
        app = QApplication.instance()
        focus_widget = app.focusWidget() if app is not None else None
        if self.is_add_category_widget(focus_widget):
            return
        self.cancel_add_category()

    def is_add_category_widget(self, widget: QWidget | None) -> bool:
        current = widget
        while current is not None:
            if current is self.window._add_category_row:
                return True
            current = current.parentWidget()
        return False

    def create_route_checkbox(self, name: str) -> QCheckBox:
        checkbox = ElidedCheckBox(name)
        checkbox.setMinimumHeight(theme.RECENT_ROUTE_ITEM_HEIGHT)
        checkbox.setChecked(self.window.route_mgr.visibility.get(name, False))
        checkbox.toggled.connect(
            lambda enabled, route_name=name, source=checkbox: self.toggle_route(route_name, enabled, source)
        )
        self.window._route_checkboxes.setdefault(name, []).append(checkbox)
        return checkbox

    @staticmethod
    def route_checkbox_name(checkbox: QCheckBox) -> str:
        if isinstance(checkbox, ElidedCheckBox):
            return checkbox.full_text()
        return checkbox.text()

    def begin_route_rename(self, route_item: RouteListItem) -> None:
        if self.window._active_route_rename_item is not None and self.window._active_route_rename_item is not route_item:
            self.window._active_route_rename_item.cancel_rename()
        self.window._active_route_rename_item = route_item
        route_item.start_rename()

    def cancel_active_route_rename(self) -> None:
        if self.window._active_route_rename_item is None:
            return
        self.window._active_route_rename_item.cancel_rename()
        self.window._active_route_rename_item = None

    def confirm_route_rename(self, route_item: RouteListItem) -> None:
        new_name = route_item.current_rename_value()
        if not new_name:
            route_item.show_rename_error("路线名称不能为空")
            return
        if not self.window.route_mgr.rename_route(route_item.category, route_item.route_name, new_name):
            route_item.show_rename_error("名称无效或已存在")
            return
        self.replace_recent_route_name(route_item.route_name, new_name)
        self.window._active_route_rename_item = None
        self.reload_route_list()

    def delete_route(self, category: str, name: str) -> None:
        confirmed = styled_confirm(
            self.window,
            "删除路线",
            f"确认删除路线“{name}”吗？",
            confirm_text="删除",
            cancel_text="取消",
        )
        if not confirmed:
            return
        if not self.window.route_mgr.delete_route(category, name):
            return
        self.remove_recent_route_name(name)
        self.cancel_active_route_rename()
        self.reload_route_list()

    def remove_recent_widgets(self) -> None:
        while self.window.recent_routes_layout.count():
            item = self.window.recent_routes_layout.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            if isinstance(widget, QCheckBox):
                self.unregister_route_checkbox(self.route_checkbox_name(widget), widget)
            widget.deleteLater()

    def remove_tracked_route_widgets(self) -> None:
        while self.window.tracked_routes_grid.count():
            item = self.window.tracked_routes_grid.takeAt(0)
            widget = item.widget()
            if widget is None:
                continue
            checkbox = self.tracked_widget_checkbox(widget)
            if checkbox is not None:
                self.unregister_route_checkbox(self.route_checkbox_name(checkbox), checkbox)
            widget.deleteLater()

    def refresh_recent_routes(self) -> None:
        self.remove_recent_widgets()

        search_term = self.window.search_input.text().strip().casefold()
        route_names = [
            name for name in self.window._recent_route_names if self.matches_route(name, search_term)
        ]
        if self.window._recent_limit:
            route_names = route_names[: self.window._recent_limit]
        else:
            route_names = []

        if route_names:
            for name in route_names:
                self.window.recent_routes_layout.addWidget(self.create_route_checkbox(name))
        else:
            hint = QLabel("暂无最近常用路线")
            hint.setObjectName("EmptyHint")
            hint.setMinimumHeight(theme.RECENT_ROUTE_ITEM_HEIGHT)
            hint.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self.window.recent_routes_layout.addWidget(hint)
        self.window.recent_routes_layout.addStretch()
        self.window.recent_scroll_inner.adjustSize()
        self.sync_recent_scroll_height(len(route_names) if route_names else 1)

    def sync_recent_scroll_height(self, item_count: int) -> None:
        rows = max(1, item_count)
        spacing = self.window.recent_routes_layout.spacing()
        content_height = rows * theme.RECENT_ROUTE_ITEM_HEIGHT + max(0, rows - 1) * spacing
        target_height = min(theme.RECENT_ROUTES_MAX_HEIGHT, content_height)
        self.window.recent_scroll.setFixedHeight(target_height)
        card_height = target_height + theme.RECENT_ROUTE_CARD_PADDING
        self.window.recent_card.setMinimumHeight(card_height)
        self.window.recent_card.setMaximumHeight(card_height)

    def unregister_route_checkbox(self, name: str, checkbox: QCheckBox) -> None:
        widgets = self.window._route_checkboxes.get(name)
        if not widgets:
            return
        if checkbox in widgets:
            widgets.remove(checkbox)
        if not widgets:
            self.window._route_checkboxes.pop(name, None)

    def toggle_route(self, name: str, enabled: bool, source: QCheckBox) -> None:
        self.window.route_mgr.visibility[name] = enabled
        if enabled:
            self.remember_recent_route(name)
        self.window.route_mgr.save_visibility()
        self.sync_route_checkboxes(name, enabled, source)
        self.refresh_tracked_routes()
        self.refresh_recent_routes()

    def sync_route_checkboxes(self, name: str, enabled: bool, source: QCheckBox) -> None:
        for checkbox in list(self.window._route_checkboxes.get(name, [])):
            if checkbox is source:
                continue
            checkbox.blockSignals(True)
            checkbox.setChecked(enabled)
            checkbox.blockSignals(False)

    def refresh_tracked_routes(self) -> None:
        route_names = self.window.route_mgr.visible_route_names()
        self.window.tracked_routes_title.setText(f"当前追踪路线 ({len(route_names)})")
        self.remove_tracked_route_widgets()

        if route_names:
            for index, name in enumerate(route_names):
                route_item = TrackedRouteItem(
                    name,
                    self.window.route_mgr.visibility.get(name, False),
                    self.window.route_mgr.has_progress(name),
                )
                route_item.checkbox.toggled.connect(
                    lambda enabled, route_name=name, source=route_item.checkbox: self.toggle_route(route_name, enabled, source)
                )
                route_item.reset_btn.clicked.connect(
                    lambda _checked=False, route_name=name: self.reset_route_progress(route_name)
                )
                self.window._route_checkboxes.setdefault(name, []).append(route_item.checkbox)
                row = index // 2
                column = index % 2
                self.window.tracked_routes_grid.addWidget(route_item, row, column)
        else:
            empty_label = QLabel("暂无已选择路线")
            empty_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            empty_label.setStyleSheet(f"font-size: 12px; color: {theme.FG_DIM};")
            self.window.tracked_routes_grid.addWidget(empty_label, 0, 0, 1, 2)

        self.window._tracked_route_progress_signature = self.build_tracked_route_progress_signature(route_names)
        self.window.tracked_routes_inner.adjustSize()
        self.sync_tracked_routes_height(len(route_names))
        self.window.window_mode_controller.schedule_layout_refresh()

    @staticmethod
    def tracked_widget_checkbox(widget: QWidget) -> QCheckBox | None:
        if isinstance(widget, QCheckBox):
            return widget
        checkbox = getattr(widget, "checkbox", None)
        return checkbox if isinstance(checkbox, QCheckBox) else None

    def build_tracked_route_progress_signature(
        self,
        route_names: list[str] | None = None,
    ) -> tuple[tuple[str, bool], ...]:
        names = route_names if route_names is not None else self.window.route_mgr.visible_route_names()
        return tuple((name, self.window.route_mgr.has_progress(name)) for name in names)

    def reset_route_progress(self, name: str) -> None:
        self.window.route_mgr.reset_progress(name)
        self.window.map_view._refresh_from_last_frame()
        self.refresh_tracked_routes()
        toast(self.window, f"已重置路线“{name}”进度")

    def sync_tracked_routes_height(self, item_count: int) -> None:
        rows = max(1, (max(1, item_count) + 1) // 2)
        spacing = self.window.tracked_routes_grid.verticalSpacing()
        content_height = rows * theme.RECENT_ROUTE_ITEM_HEIGHT + max(0, rows - 1) * spacing
        target_height = min(theme.TRACKED_ROUTES_MAX_HEIGHT, content_height)
        self.window.tracked_routes_scroll.setFixedHeight(target_height)
        margins = self.window.tracked_routes_layout.contentsMargins()
        card_height = (
            margins.top()
            + self.window.tracked_routes_title.sizeHint().height()
            + self.window.tracked_routes_layout.spacing()
            + target_height
            + margins.bottom()
        )
        self.window.tracked_routes_card.setMinimumHeight(card_height)
        self.window.tracked_routes_card.setMaximumHeight(card_height)

    def apply_route_filter(self) -> None:
        term = self.window.search_input.text().strip().casefold()
        for category, section in self.window._route_sections.items():
            visible_count = 0
            for route_name, route_item in self.window._route_widgets_by_category[category]:
                visible = self.matches_route(route_name, term)
                route_item.setVisible(visible)
                if visible:
                    visible_count += 1
            has_routes = bool(self.window._route_widgets_by_category[category])
            section.setVisible((not has_routes) or visible_count > 0)
            section.set_force_open(bool(term) and visible_count > 0)
        self.refresh_recent_routes()
