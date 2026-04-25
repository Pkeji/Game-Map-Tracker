"""Helpers for annotation type selection and recency ordering."""

from __future__ import annotations

COMMON_TYPE_NAMES = ["魔力之源（传送点）", "宝箱", "矿石", "魔法石", "精灵的宝藏"]
RECENT_TYPE_LIMIT = 12


def normalize_type_ids(values: object) -> list[str]:
    if not isinstance(values, list):
        return []
    result = []
    seen = set()
    for value in values:
        type_id = str(value or "").strip()
        if not type_id or type_id in seen:
            continue
        seen.add(type_id)
        result.append(type_id)
    return result


def touch_recent_type(type_ids: list[str], type_id: str, limit: int = RECENT_TYPE_LIMIT) -> list[str]:
    key = str(type_id or "").strip()
    existing = normalize_type_ids(type_ids)
    if not key:
        return existing[:limit]
    return [key] + [item for item in existing if item != key][: max(0, limit - 1)]


def common_annotation_types(
    types: list[dict],
    selected_type_ids: list[str],
    recent_type_ids: list[str],
    *,
    limit: int = RECENT_TYPE_LIMIT,
) -> list[dict]:
    by_id = {str(item.get("typeId") or ""): item for item in types if item.get("typeId")}
    by_name = {str(item.get("type") or ""): item for item in types if item.get("type")}
    result = []
    seen = set()

    def add(type_id: str) -> None:
        if len(result) >= limit or not type_id or type_id in seen:
            return
        item = by_id.get(type_id)
        if item is None:
            return
        seen.add(type_id)
        result.append(item)

    for type_id in normalize_type_ids(recent_type_ids):
        add(type_id)
    for type_id in normalize_type_ids(selected_type_ids):
        add(type_id)
    for name in COMMON_TYPE_NAMES:
        item = by_name.get(name)
        if item is not None:
            add(str(item.get("typeId") or ""))
    for item in sorted(types, key=lambda value: int(value.get("count") or 0), reverse=True):
        add(str(item.get("typeId") or ""))
    return result
