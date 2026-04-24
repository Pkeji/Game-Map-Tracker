"""Controller that glues map interactions (right-click insert) to RouteManager."""

from __future__ import annotations

from typing import TYPE_CHECKING

from ..design import strings
from ..dialogs import toast
from ..dialogs.insert_point_dialog import open_insert_point_dialog
from ..dialogs.settings_dialog import styled_confirm, styled_info

if TYPE_CHECKING:
    from ..app.window import IslandWindow


class MapInteractionController:
    def __init__(self, window: "IslandWindow") -> None:
        self.window = window

    def on_add_point_requested(self, x: int, y: int) -> None:
        self.add_point_to_routes(x, y)

    def on_delete_point_requested(self, route_id: str, point_index: int) -> None:
        self.delete_points_from_routes({route_id: [point_index]})

    def delete_points_from_routes(self, deletions: dict[str, list[int]]) -> None:
        """可复用的批量删除入口:命中节点右键、未来的批量选择器都走这里。
        负责 confirm + 调用数据层 + toast 反馈 + 视图刷新。
        """
        route_mgr = self.window.route_mgr
        normalized: dict[str, list[int]] = {}
        for rid, idx_list in (deletions or {}).items():
            if not rid:
                continue
            idx_clean = [i for i in (idx_list or []) if isinstance(i, int) and not isinstance(i, bool)]
            if idx_clean:
                normalized[rid] = sorted(set(idx_clean))
        if not normalized:
            return

        requested = sum(len(v) for v in normalized.values())
        route_count = len(normalized)
        if route_count == 1:
            only_rid, only_idx = next(iter(normalized.items()))
            summary = route_mgr.summarize_route(only_rid)
            name = summary["display_label"] if summary else ""
            if len(only_idx) == 1:
                body = strings.DELETE_POINT_SINGLE_BODY_FMT.format(name=name, pos=only_idx[0] + 1)
            else:
                body = strings.DELETE_POINT_MULTI_SINGLE_ROUTE_FMT.format(name=name, count=len(only_idx))
        else:
            body = strings.DELETE_POINT_MULTI_ROUTES_FMT.format(routes=route_count, count=requested)

        confirmed = styled_confirm(
            self.window,
            strings.DELETE_POINT_TITLE,
            body,
            confirm_text=strings.DELETE_POINT_CONFIRM,
            cancel_text=strings.DELETE_POINT_CANCEL,
        )
        if not confirmed:
            return

        outcomes = route_mgr.delete_points_from_routes(normalized)
        ok_count = sum(len(v) for v in outcomes.values())
        fail_count = requested - ok_count

        if ok_count == 0:
            styled_info(
                self.window,
                strings.DELETE_POINT_FAIL_TITLE,
                strings.DELETE_POINT_FAIL_BODY,
            )
            return

        if fail_count > 0:
            toast(self.window, strings.DELETE_POINT_PARTIAL_FMT.format(ok=ok_count, fail=fail_count))
        else:
            toast(self.window, strings.DELETE_POINT_SUCCESS_FMT.format(count=ok_count))

        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass
        try:
            self.window.route_panel_controller.refresh_tracked_routes()
        except Exception:
            pass

    def add_point_to_routes(
        self,
        x: int,
        y: int,
        route_ids: list[str] | None = None,
        show_dialog: bool = True,
    ) -> None:
        """可复用入口:右键菜单与未来的"加入玩家定位"按钮都走这里。
        route_ids=None 时默认所有当前可见(追踪中)的路线。
        """
        route_mgr = self.window.route_mgr
        if route_ids is None:
            candidate_ids = route_mgr.visible_route_ids()
        else:
            candidate_ids = [rid for rid in route_ids if rid]

        if not candidate_ids:
            styled_info(
                self.window,
                strings.INSERT_POINT_EMPTY_TITLE,
                strings.INSERT_POINT_EMPTY_BODY,
            )
            return

        candidates = []
        for rid in candidate_ids:
            summary = route_mgr.summarize_route(rid)
            if summary is None:
                continue
            suggested = route_mgr.suggest_insertion_index(rid, x, y)
            if suggested is None:
                suggested = summary["points_count"]
            candidates.append({
                "route_id": rid,
                "display_label": summary["display_label"],
                "points_count": summary["points_count"],
                "suggested_index": int(suggested),
            })

        if not candidates:
            styled_info(
                self.window,
                strings.INSERT_POINT_EMPTY_TITLE,
                strings.INSERT_POINT_EMPTY_BODY,
            )
            return

        if show_dialog:
            result = open_insert_point_dialog(self.window, x, y, candidates)
            if result is None:
                return
            selected_ids, overrides = result
            if not selected_ids:
                return
        else:
            selected_ids = [candidate["route_id"] for candidate in candidates]
            overrides = {}

        if show_dialog and len(selected_ids) > 1:
            confirmed = styled_confirm(
                self.window,
                strings.INSERT_POINT_MULTI_WARN_TITLE,
                strings.INSERT_POINT_MULTI_WARN_BODY,
                confirm_text=strings.INSERT_POINT_CONFIRM,
                cancel_text=strings.INSERT_POINT_CANCEL,
            )
            if not confirmed:
                return

        outcomes = route_mgr.insert_point_into_routes(x, y, selected_ids, overrides)
        ok_count = sum(1 for v in outcomes.values() if v is not None)
        fail_count = len(outcomes) - ok_count

        if ok_count == 0:
            styled_info(
                self.window,
                strings.INSERT_POINT_FAIL_TITLE,
                strings.INSERT_POINT_FAIL_BODY,
            )
            return

        if fail_count > 0:
            toast(self.window, strings.INSERT_POINT_PARTIAL_FMT.format(ok=ok_count, fail=fail_count))
        else:
            toast(self.window, strings.INSERT_POINT_SUCCESS_FMT.format(count=ok_count))

        try:
            self.window.map_view._refresh_from_last_frame()
        except Exception:
            pass
        try:
            self.window.route_panel_controller.refresh_tracked_routes()
        except Exception:
            pass
