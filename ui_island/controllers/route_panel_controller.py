"""Route panel and route list orchestration."""

from __future__ import annotations

import os
import subprocess
import sys

from PySide6.QtCore import QTimer, Qt
from PySide6.QtWidgets import QApplication, QCheckBox, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QWidget

from ..design import strings, theme
from ..dialogs import toast
from ..dialogs.route_notes_dialog import edit_route_notes
from ..dialogs.settings_dialog import styled_confirm, styled_info
from ..dialogs.text_input_dialog import prompt_text_input
from ..widgets import ElidedCheckBox, RouteListItem, RouteSection, TrackedRouteItem
from ..widgets.context_menu import ContextMenuItem, show_context_menu
from ..widgets.factory import make_header_icon_button


class RoutePanelController:
    def __init__(self, window) -> None:
        self.window = window
        self.state = window.route_panel_state

    def save_recent_routes(self) -> None:
        self.window.recent_routes_store.save(self.window._recent_route_names)

    def remember_recent_route(self, route_id: str) -> None:
        recent_route_names = self.window._recent_route_names
        if route_id in recent_route_names:
            recent_route_names.remove(route_id)
        recent_route_names.insert(0, route_id)
        self.save_recent_routes()

    def remove_recent_route_name(self, route_id: str) -> None:
        self.window._recent_route_names[:] = [
            known_route_id for known_route_id in self.window._recent_route_names if known_route_id != route_id
        ]
        self.save_recent_routes()

    @staticmethod
    def matches_route(route_name: str, term: str) -> bool:
        return not term or term in route_name.casefold()

    def resolve_route_section_expanded(self, category: str) -> bool:
        return bool(self.window._route_section_expanded.get(category, False))

    def remember_route_section_states_from_widgets(self) -> None:
        for category, section in self.window._route_sections.items():
            self.window._route_section_expanded[category] = section.is_expanded()

    def save_route_section_expanded(self) -> None:
        self.remember_route_section_states_from_widgets()
        try:
            self.window.window_prefs_store.save_route_section_expanded(dict(self.window._route_section_expanded))
        except Exception as e:
            print(f"Save route section expanded state failed: {e}")

    def handle_route_section_toggled(self, category: str, expanded: bool) -> None:
        self.window._route_section_expanded[category] = bool(expanded)
        self.save_route_section_expanded()

    def build_add_category_row(self) -> None:
        add_category_row = QFrame()
        add_category_row.setObjectName("PanelCard")
        add_category_row.hide()

        row_layout = QHBoxLayout(add_category_row)
        row_layout.setContentsMargins(8, 8, 8, 8)
        row_layout.setSpacing(6)

        add_category_input = QLineEdit()
        add_category_input.setPlaceholderText(strings.ROUTE_ADD_CATEGORY_PLACEHOLDER)
        add_category_input.returnPressed.connect(self.confirm_add_category)
        add_category_input.editingFinished.connect(self.queue_cancel_add_category_if_needed)
        row_layout.addWidget(add_category_input, stretch=1)

        add_category_confirm_btn = make_header_icon_button(
            "✓",
            role="confirm",
            tooltip=strings.ROUTE_ADD_CATEGORY_CONFIRM,
            width=30,
        )
        add_category_confirm_btn.clicked.connect(self.confirm_add_category)
        row_layout.addWidget(add_category_confirm_btn)

        add_category_cancel_btn = make_header_icon_button(
            "×",
            role="close",
            tooltip=strings.ROUTE_ADD_CATEGORY_CANCEL,
            width=30,
        )
        add_category_cancel_btn.clicked.connect(self.cancel_add_category)
        row_layout.addWidget(add_category_cancel_btn)

        self.window._add_category_row = add_category_row
        self.window._add_category_input = add_category_input
        self.window._add_category_confirm_btn = add_category_confirm_btn
        self.window._add_category_cancel_btn = add_category_cancel_btn

    def build_route_sections(self) -> None:
        for category in self.window.route_mgr.categories:
            section = RouteSection(category)
            section.set_expanded(self.resolve_route_section_expanded(category))
            self.window._route_sections[category] = section
            self.window._route_widgets_by_category[category] = []
            section.header.toggled.connect(
                lambda expanded, cat=category: self.handle_route_section_toggled(cat, expanded)
            )
            section.context_menu_requested.connect(
                lambda global_pos, cat=category: self.show_category_context_menu(cat, global_pos)
            )

            section.add_route_btn.clicked.connect(
                lambda _checked=False, cat=category: self.show_add_route_row(cat)
            )
            section.add_route_confirm_btn.clicked.connect(
                lambda _checked=False, cat=category: self.confirm_add_route(cat)
            )
            section.add_route_cancel_btn.clicked.connect(
                lambda _checked=False, cat=category: self.cancel_add_route(cat)
            )
            section.add_route_input.returnPressed.connect(
                lambda cat=category: self.confirm_add_route(cat)
            )

            routes = sorted(
                self.window.route_mgr.route_groups[category],
                key=lambda route: route.get("display_name", ""),
            )
            for route in routes:
                route_id = self.window.route_mgr.route_id(route)
                name = route.get("display_name", "")
                route_item = self.create_route_list_item(category, route)
                section.add_widget(route_item)
                self.window._route_widgets_by_category[category].append((route_id, name, route_item))

            self.window.routes_layout.addWidget(section)

    def clear_route_sections(self) -> None:
        for route_widgets in self.window._route_widgets_by_category.values():
            for route_id, _name, route_item in route_widgets:
                self.unregister_route_checkbox(route_id, route_item.checkbox)

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
        self.remember_route_section_states_from_widgets()
        self.clear_route_sections()
        if self.window._add_category_row is not None:
            self.window.routes_layout.addWidget(self.window._add_category_row)
        self.build_route_sections()
        self.window.routes_layout.addStretch()
        self.window.routes_scroll_inner.adjustSize()
        self.window.interaction_controller.install_resize_filters(self.window.routes_scroll_inner)

    def reload_route_list(self) -> None:
        self.remember_route_section_states_from_widgets()
        self.cancel_active_route_rename()
        self.window.route_mgr.reload()
        known_routes = {
            self.window.route_mgr.route_id(route)
            for routes in self.window.route_mgr.route_groups.values()
            for route in routes
        }
        self.window._recent_route_names[:] = [
            route_id for route_id in self.window._recent_route_names if route_id in known_routes
        ]
        self.save_recent_routes()
        self.window._route_section_expanded = {
            category: expanded
            for category, expanded in self.window._route_section_expanded.items()
            if category in self.window.route_mgr.categories
        }
        self.rebuild_route_sections()
        self.refresh_tracked_routes()
        self.apply_route_filter()
        self.window.map_view._refresh_from_last_frame()
        self.window.window_mode_controller.schedule_layout_refresh()

    def create_route_list_item(self, category: str, route: dict) -> RouteListItem:
        route_id = self.window.route_mgr.route_id(route)
        name = route.get("display_name", "")
        route_item = RouteListItem(category, route_id, name, self.window.route_mgr.visibility.get(route_id, False))
        route_item.checkbox.toggled.connect(
            lambda enabled, known_route_id=route_id, source=route_item.checkbox: self.toggle_route(known_route_id, enabled, source)
        )
        route_item.rename_confirm_btn.clicked.connect(lambda: self.confirm_route_rename(route_item))
        route_item.rename_cancel_btn.clicked.connect(self.cancel_active_route_rename)
        route_item.rename_input.returnPressed.connect(lambda: self.confirm_route_rename(route_item))
        route_item.context_menu_requested.connect(
            lambda global_pos, item=route_item: self.show_route_context_menu(item, global_pos)
        )
        self.window._route_checkboxes.setdefault(route_id, []).append(route_item.checkbox)
        return route_item

    def show_route_context_menu(self, route_item: RouteListItem, global_pos) -> None:
        show_context_menu(
            self.window,
            global_pos,
            [
                ContextMenuItem(strings.ROUTE_RENAME, lambda: self.begin_route_rename(route_item)),
                ContextMenuItem(
                    strings.ROUTE_NOTES,
                    lambda: self.show_route_notes_dialog(route_item.category, route_item.route_name),
                ),
                ContextMenuItem(
                    strings.ROUTE_DELETE,
                    lambda: self.delete_route(route_item.category, route_item.route_name),
                ),
                ContextMenuItem.separator_item(),
                ContextMenuItem(
                    strings.ROUTE_OPEN_FILE_LOCATION,
                    lambda: self.open_route_file_location(route_item.category, route_item.route_name),
                ),
            ],
        )

    def show_category_context_menu(self, category: str, global_pos) -> None:
        show_context_menu(
            self.window,
            global_pos,
            [
                ContextMenuItem(strings.ROUTE_CATEGORY_RENAME, lambda: self.rename_category(category)),
                ContextMenuItem(strings.ROUTE_CATEGORY_DELETE, lambda: self.delete_category(category)),
                ContextMenuItem.separator_item(),
                ContextMenuItem(
                    strings.ROUTE_CATEGORY_OPEN_FILE_LOCATION,
                    lambda: self.open_category_file_location(category),
                ),
            ],
        )

    def show_add_category_row(self) -> None:
        if self.window._add_category_row is None or self.window._add_category_input is None:
            return
        self.window._adding_category = True
        self.window._add_category_input.clear()
        self.window._add_category_input.setPlaceholderText(strings.ROUTE_ADD_CATEGORY_PLACEHOLDER)
        self.window._add_category_row.show()
        self.window._add_category_input.setFocus()
        self.window.window_mode_controller.schedule_layout_refresh()

    def cancel_add_category(self) -> None:
        if self.window._add_category_row is None or self.window._add_category_input is None:
            return
        self.window._adding_category = False
        self.window._add_category_input.clear()
        self.window._add_category_input.setPlaceholderText(strings.ROUTE_ADD_CATEGORY_PLACEHOLDER)
        self.window._add_category_row.hide()
        self.window.window_mode_controller.schedule_layout_refresh()

    def confirm_add_category(self) -> None:
        if self.window._add_category_input is None:
            return
        name = self.window._add_category_input.text().strip()
        if not name:
            self.window._add_category_input.clear()
            self.window._add_category_input.setPlaceholderText(strings.ROUTE_CATEGORY_EMPTY)
            self.window._add_category_input.setFocus()
            return
        if not self.window.route_mgr.create_category(name):
            self.window._add_category_input.selectAll()
            self.window._add_category_input.setPlaceholderText(strings.ROUTE_CATEGORY_INVALID)
            self.window._add_category_input.setFocus()
            return
        self.cancel_add_category()
        self.reload_route_list()

    def show_add_route_row(self, category: str) -> None:
        section = self.window._route_sections.get(category)
        if section is None:
            return
        for cat, other in self.window._route_sections.items():
            if cat != category and other.is_adding_route():
                other.hide_add_route_row()
        section.show_add_route_row()
        self.window.window_mode_controller.schedule_layout_refresh()

    def cancel_add_route(self, category: str) -> None:
        section = self.window._route_sections.get(category)
        if section is None:
            return
        section.hide_add_route_row()
        self.window.window_mode_controller.schedule_layout_refresh()

    def confirm_add_route(self, category: str) -> None:
        section = self.window._route_sections.get(category)
        if section is None:
            return
        name = section.current_add_route_name()
        if not name:
            section.show_add_route_error(strings.ROUTE_RENAME_EMPTY)
            return
        if not self.window.route_mgr.create_route(category, name):
            section.show_add_route_error(strings.ROUTE_RENAME_INVALID)
            return
        section.hide_add_route_row()
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

    def create_route_checkbox(self, route_id: str, route_name: str) -> QCheckBox:
        checkbox = ElidedCheckBox(route_name)
        checkbox.setMinimumHeight(theme.RECENT_ROUTE_ITEM_HEIGHT)
        checkbox.setProperty("routeId", route_id)
        checkbox.setChecked(self.window.route_mgr.visibility.get(route_id, False))
        checkbox.toggled.connect(
            lambda enabled, known_route_id=route_id, source=checkbox: self.toggle_route(known_route_id, enabled, source)
        )
        self.window._route_checkboxes.setdefault(route_id, []).append(checkbox)
        return checkbox

    @staticmethod
    def route_checkbox_name(checkbox: QCheckBox) -> str:
        route_id = checkbox.property("routeId")
        if isinstance(route_id, str) and route_id:
            return route_id
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
            route_item.show_rename_error(strings.ROUTE_RENAME_EMPTY)
            return
        if not self.window.route_mgr.rename_route(route_item.category, route_item.route_name, new_name):
            route_item.show_rename_error(strings.ROUTE_RENAME_INVALID)
            return
        self.window._active_route_rename_item = None
        self.reload_route_list()

    def rename_category(self, category: str) -> None:
        accepted, new_name = prompt_text_input(
            self.window,
            title=strings.ROUTE_CATEGORY_RENAME_TITLE,
            label=f"当前分类：{category}",
            value=category,
            placeholder=strings.ROUTE_CATEGORY_RENAME_PLACEHOLDER,
            confirm_text=strings.ROUTE_CATEGORY_RENAME_CONFIRM,
            cancel_text=strings.ROUTE_CATEGORY_RENAME_CANCEL,
        )
        if not accepted:
            return
        if not new_name:
            styled_info(self.window, strings.ROUTE_CATEGORY_RENAME_TITLE, strings.ROUTE_CATEGORY_RENAME_EMPTY)
            return
        if not self.window.route_mgr.rename_category(category, new_name):
            styled_info(self.window, strings.ROUTE_CATEGORY_RENAME_TITLE, strings.ROUTE_CATEGORY_RENAME_INVALID)
            return

        self.window._route_section_expanded[new_name] = self.window._route_section_expanded.pop(
            category,
            self.resolve_route_section_expanded(category),
        )
        self.reload_route_list()

    def show_route_notes_dialog(self, category: str, name: str) -> None:
        current_notes = self.window.route_mgr.get_route_notes(category, name)
        accepted, notes = edit_route_notes(self.window, name, current_notes)
        if not accepted or notes == current_notes:
            return
        if not self.window.route_mgr.update_route_notes(category, name, notes):
            styled_info(self.window, strings.ROUTE_NOTES_TITLE, strings.ROUTE_NOTES_SAVE_FAILED.format(name=name))
            return
        toast(self.window, strings.ROUTE_NOTES_SAVED.format(name=name))

    def delete_route(self, category: str, name: str) -> None:
        route_id = next(
            (
                self.window.route_mgr.route_id(route)
                for route in self.window.route_mgr.route_groups.get(category, [])
                if route.get("display_name") == name
            ),
            None,
        )
        confirmed = styled_confirm(
            self.window,
            strings.ROUTE_DELETE_TITLE,
            strings.ROUTE_DELETE_MESSAGE.format(name=name),
            confirm_text=strings.ROUTE_DELETE_CONFIRM,
            cancel_text=strings.ROUTE_DELETE_CANCEL,
        )
        if not confirmed:
            return
        if not self.window.route_mgr.delete_route(category, name):
            return
        if route_id:
            self.remove_recent_route_name(route_id)
        self.cancel_active_route_rename()
        self.reload_route_list()

    def delete_category(self, category: str) -> None:
        confirmed = styled_confirm(
            self.window,
            strings.ROUTE_CATEGORY_DELETE_TITLE,
            strings.ROUTE_CATEGORY_DELETE_MESSAGE.format(name=category),
            confirm_text=strings.ROUTE_CATEGORY_DELETE_CONFIRM,
            cancel_text=strings.ROUTE_CATEGORY_DELETE_CANCEL,
        )
        if not confirmed:
            return
        if not self.window.route_mgr.delete_category(category):
            return
        self.window._route_section_expanded.pop(category, None)
        self.cancel_active_route_rename()
        self.reload_route_list()

    def open_route_file_location(self, category: str, name: str) -> None:
        path = self.window.route_mgr.route_file_path(category, name)
        try:
            if not os.path.exists(path):
                raise FileNotFoundError(path)
            if sys.platform.startswith("win"):
                try:
                    subprocess.Popen(["explorer", "/select,", os.path.normpath(path)])
                except OSError:
                    os.startfile(os.path.dirname(path))
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                if not QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.dirname(path))):
                    raise OSError(path)
        except Exception:
            styled_info(
                self.window,
                strings.ROUTE_OPEN_FILE_LOCATION,
                strings.ROUTE_OPEN_FILE_LOCATION_FAILED.format(name=name),
            )

    def open_category_file_location(self, category: str) -> None:
        path = self.window.route_mgr.category_path(category)
        try:
            if not os.path.isdir(path):
                raise FileNotFoundError(path)
            if sys.platform.startswith("win"):
                os.startfile(path)
            else:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices

                if not QDesktopServices.openUrl(QUrl.fromLocalFile(path)):
                    raise OSError(path)
        except Exception:
            styled_info(
                self.window,
                strings.ROUTE_CATEGORY_OPEN_FILE_LOCATION,
                strings.ROUTE_CATEGORY_OPEN_FILE_LOCATION_FAILED.format(name=category),
            )

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
        recent_routes = [
            (route_id, self.window.route_mgr.route_name_for_id(route_id))
            for route_id in self.window._recent_route_names
            if self.window.route_mgr.route_name_for_id(route_id)
        ]
        recent_routes = [
            (route_id, route_name)
            for route_id, route_name in recent_routes
            if self.matches_route(route_name, search_term)
        ]
        if self.window._recent_limit:
            recent_routes = recent_routes[: self.window._recent_limit]
        else:
            recent_routes = []

        if recent_routes:
            for route_id, route_name in recent_routes:
                self.window.recent_routes_layout.addWidget(self.create_route_checkbox(route_id, route_name))
        else:
            hint = QLabel(strings.ROUTE_EMPTY_RECENT)
            hint.setObjectName("EmptyHint")
            hint.setMinimumHeight(theme.RECENT_ROUTE_ITEM_HEIGHT)
            hint.setAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            self.window.recent_routes_layout.addWidget(hint)
        self.window.recent_routes_layout.addStretch()
        self.window.recent_scroll_inner.adjustSize()
        self.sync_recent_scroll_height(len(recent_routes) if recent_routes else 1)

    def sync_recent_scroll_height(self, item_count: int) -> None:
        rows = max(1, item_count)
        spacing = self.window.recent_routes_layout.spacing()
        content_height = rows * theme.RECENT_ROUTE_ITEM_HEIGHT + max(0, rows - 1) * spacing
        target_height = min(theme.RECENT_ROUTES_MAX_HEIGHT, content_height)
        self.window.recent_scroll.setFixedHeight(target_height)
        card_height = target_height + theme.RECENT_ROUTE_CARD_PADDING
        self.window.recent_card.setMinimumHeight(card_height)
        self.window.recent_card.setMaximumHeight(card_height)

    def unregister_route_checkbox(self, route_id: str, checkbox: QCheckBox) -> None:
        widgets = self.window._route_checkboxes.get(route_id)
        if not widgets:
            return
        if checkbox in widgets:
            widgets.remove(checkbox)
        if not widgets:
            self.window._route_checkboxes.pop(route_id, None)

    def toggle_route(self, route_id: str, enabled: bool, source: QCheckBox) -> None:
        self.window.route_mgr.visibility[route_id] = enabled
        if enabled:
            self.remember_recent_route(route_id)
        self.window.route_mgr.save_visibility()
        self.sync_route_checkboxes(route_id, enabled, source)
        self.refresh_tracked_routes()
        self.refresh_recent_routes()
        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass

    def sync_route_checkboxes(self, route_id: str, enabled: bool, source: QCheckBox) -> None:
        for checkbox in list(self.window._route_checkboxes.get(route_id, [])):
            if checkbox is source:
                continue
            checkbox.blockSignals(True)
            checkbox.setChecked(enabled)
            checkbox.blockSignals(False)

    def refresh_tracked_routes(self) -> None:
        visible_routes = self.window.route_mgr.visible_routes()
        self.window.tracked_routes_title.setText(f"{strings.ROUTE_TRACKED_TITLE} ({len(visible_routes)})")
        self.remove_tracked_route_widgets()

        if visible_routes:
            for index, route in enumerate(visible_routes):
                route_id = self.window.route_mgr.route_id(route)
                route_name = route.get("display_name", "")
                route_item = TrackedRouteItem(
                    route_id,
                    route_name,
                    self.window.route_mgr.visibility.get(route_id, False),
                    self.window.route_mgr.has_progress(route_id),
                )
                route_item.checkbox.toggled.connect(
                    lambda enabled, known_route_id=route_id, source=route_item.checkbox: self.toggle_route(known_route_id, enabled, source)
                )
                route_item.reset_btn.clicked.connect(
                    lambda _checked=False, known_route_id=route_id: self.reset_route_progress(known_route_id)
                )
                route_item.add_point_btn.clicked.connect(
                    lambda _checked=False, known_route_id=route_id: self.add_current_position_to_route(known_route_id)
                )
                self.window._route_checkboxes.setdefault(route_id, []).append(route_item.checkbox)
                row = index // 2
                column = index % 2
                self.window.tracked_routes_grid.addWidget(route_item, row, column)
        else:
            empty_label = QLabel(strings.ROUTE_EMPTY_TRACKED)
            empty_label.setAlignment(Qt.AlignTop | Qt.AlignLeft)
            empty_label.setStyleSheet(f"font-size: 12px; color: {theme.FG_DIM};")
            self.window.tracked_routes_grid.addWidget(empty_label, 0, 0, 1, 2)

        tracked_route_ids = [self.window.route_mgr.route_id(route) for route in visible_routes]
        self.window._tracked_route_progress_signature = self.build_tracked_route_progress_signature(tracked_route_ids)
        self.window.tracked_routes_inner.adjustSize()
        self.sync_tracked_routes_height(len(visible_routes))
        self.window.window_mode_controller.schedule_layout_refresh()

    @staticmethod
    def tracked_widget_checkbox(widget: QWidget) -> QCheckBox | None:
        if isinstance(widget, QCheckBox):
            return widget
        checkbox = getattr(widget, "checkbox", None)
        return checkbox if isinstance(checkbox, QCheckBox) else None

    def build_tracked_route_progress_signature(
        self,
        route_ids: list[str] | None = None,
    ) -> tuple[tuple[str, bool], ...]:
        ids = route_ids if route_ids is not None else self.window.route_mgr.visible_route_ids()
        return tuple((route_id, self.window.route_mgr.has_progress(route_id)) for route_id in ids)

    def reset_route_progress(self, route_id: str) -> None:
        self.window.route_mgr.reset_progress(route_id)
        self.window.map_view._refresh_from_last_frame()
        self.refresh_tracked_routes()
        route_name = self.window.route_mgr.route_name_for_id(route_id) or route_id
        toast(self.window, f"已重置路线“{route_name}”进度")

    def add_current_position_to_route(self, route_id: str) -> None:
        player_xy = getattr(self.window, "_last_player_xy", None)
        if player_xy is None:
            styled_info(
                self.window,
                "无法添加节点",
                "当前没有可用定位，请等待定位稳定后再添加。",
            )
            return

        try:
            x, y = int(player_xy[0]), int(player_xy[1])
        except (TypeError, ValueError, IndexError):
            styled_info(
                self.window,
                "无法添加节点",
                "当前定位坐标无效，请等待定位稳定后再添加。",
            )
            return

        self.window.map_interaction_controller.add_point_to_routes(
            x,
            y,
            route_ids=[route_id],
            show_dialog=False,
        )

    def sync_tracked_routes_height(self, item_count: int) -> None:
        fit_hint = getattr(self.window, "_fit_route_guide_hint_width", None)
        if callable(fit_hint):
            fit_hint()
        rows = max(1, (max(1, item_count) + 1) // 2)
        spacing = self.window.tracked_routes_grid.verticalSpacing()
        content_height = rows * theme.RECENT_ROUTE_ITEM_HEIGHT + max(0, rows - 1) * spacing
        target_height = min(theme.TRACKED_ROUTES_MAX_HEIGHT, content_height)
        self.window.tracked_routes_scroll.setFixedHeight(target_height)
        margins = self.window.tracked_routes_layout.contentsMargins()
        card_height = (
            margins.top()
            + self.window.tracked_routes_header.sizeHint().height()
            + self.window.tracked_routes_layout.spacing()
            + target_height
            + margins.bottom()
        )
        self.window.tracked_routes_card.setMinimumHeight(card_height)
        self.window.tracked_routes_card.setMaximumHeight(card_height)

    def apply_route_filter(self) -> None:
        term = self.window.search_input.text().strip().casefold()
        has_search = bool(term)
        for category, section in self.window._route_sections.items():
            visible_count = 0
            for _route_id, route_name, route_item in self.window._route_widgets_by_category[category]:
                visible = self.matches_route(route_name, term)
                route_item.setVisible(visible)
                if visible:
                    visible_count += 1
            section.setVisible((not has_search) or visible_count > 0)
            section.set_force_open(has_search and visible_count > 0)
        self.refresh_recent_routes()
