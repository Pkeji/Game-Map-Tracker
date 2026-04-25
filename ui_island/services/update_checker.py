"""GitHub Releases based update checker."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

import requests

from ..app.app_info import APP_VERSION, UPDATE_REPO


_VERSION_RE = re.compile(r"^\s*v?(\d+)\.(\d+)\.(\d+)(?:[-+]([0-9A-Za-z.-]+))?\s*$")


@dataclass(frozen=True)
class ParsedVersion:
    major: int
    minor: int
    patch: int
    prerelease: str = ""


@dataclass(frozen=True)
class ReleaseAsset:
    name: str
    browser_download_url: str


@dataclass(frozen=True)
class ReleaseInfo:
    tag_name: str
    version: str
    html_url: str
    name: str
    body: str
    published_at: str
    assets: tuple[ReleaseAsset, ...]


@dataclass(frozen=True)
class UpdateCheckResult:
    ok: bool
    current_version: str
    has_update: bool = False
    release: ReleaseInfo | None = None
    error: str = ""


class UpdateCheckError(RuntimeError):
    """Raised when a release response cannot be used for update checks."""


def parse_version(value: str) -> ParsedVersion:
    match = _VERSION_RE.match(str(value or ""))
    if not match:
        raise ValueError(f"版本号格式无效：{value}")
    major, minor, patch, prerelease = match.groups()
    return ParsedVersion(int(major), int(minor), int(patch), prerelease or "")


def normalize_version(value: str) -> str:
    parsed = parse_version(value)
    base = f"{parsed.major}.{parsed.minor}.{parsed.patch}"
    return f"{base}-{parsed.prerelease}" if parsed.prerelease else base


def compare_versions(left: str, right: str) -> int:
    left_parsed = parse_version(left)
    right_parsed = parse_version(right)
    left_core = (left_parsed.major, left_parsed.minor, left_parsed.patch)
    right_core = (right_parsed.major, right_parsed.minor, right_parsed.patch)
    if left_core != right_core:
        return 1 if left_core > right_core else -1
    if left_parsed.prerelease == right_parsed.prerelease:
        return 0
    if not left_parsed.prerelease:
        return 1
    if not right_parsed.prerelease:
        return -1
    return 1 if _prerelease_key(left_parsed.prerelease) > _prerelease_key(right_parsed.prerelease) else -1


def _prerelease_key(value: str) -> tuple[tuple[int, int | str], ...]:
    parts: list[tuple[int, int | str]] = []
    for part in re.split(r"[.-]", value):
        if part.isdigit():
            parts.append((0, int(part)))
        else:
            parts.append((1, part.lower()))
    return tuple(parts)


def parse_release(payload: dict[str, Any]) -> ReleaseInfo:
    if not isinstance(payload, dict) or not payload:
        raise UpdateCheckError("GitHub Release 响应为空。")

    tag_name = str(payload.get("tag_name") or "").strip()
    if not tag_name:
        raise UpdateCheckError("GitHub Release 缺少 tag_name。")

    try:
        version = normalize_version(tag_name)
    except ValueError as exc:
        raise UpdateCheckError(str(exc)) from exc

    assets = []
    for item in payload.get("assets") or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or "").strip()
        url = str(item.get("browser_download_url") or "").strip()
        if name or url:
            assets.append(ReleaseAsset(name=name, browser_download_url=url))

    return ReleaseInfo(
        tag_name=tag_name,
        version=version,
        html_url=str(payload.get("html_url") or "").strip(),
        name=str(payload.get("name") or tag_name).strip(),
        body=str(payload.get("body") or "").strip(),
        published_at=str(payload.get("published_at") or "").strip(),
        assets=tuple(assets),
    )


def check_for_updates(
    *,
    current_version: str = APP_VERSION,
    repo: str = UPDATE_REPO,
    timeout: float = 10.0,
    session: Any | None = None,
) -> UpdateCheckResult:
    try:
        normalize_version(current_version)
    except ValueError as exc:
        return UpdateCheckResult(ok=False, current_version=current_version, error=f"本地{exc}")

    client = session or requests
    url = f"https://api.github.com/repos/{repo}/releases/latest"
    try:
        response = client.get(
            url,
            timeout=timeout,
            headers={
                "Accept": "application/vnd.github+json",
                "User-Agent": "GMT-N update checker",
            },
        )
    except requests.RequestException as exc:
        return UpdateCheckResult(
            ok=False,
            current_version=current_version,
            error=f"无法连接 GitHub：{exc}",
        )

    status_code = int(getattr(response, "status_code", 0) or 0)
    if status_code == 404:
        return UpdateCheckResult(
            ok=False,
            current_version=current_version,
            error="未找到 GitHub Release，请先在仓库发布一个版本。",
        )
    if status_code != 200:
        return UpdateCheckResult(
            ok=False,
            current_version=current_version,
            error=f"GitHub API 返回 HTTP {status_code}。",
        )

    try:
        release = parse_release(response.json())
    except (ValueError, UpdateCheckError) as exc:
        return UpdateCheckResult(ok=False, current_version=current_version, error=str(exc))

    return UpdateCheckResult(
        ok=True,
        current_version=normalize_version(current_version),
        has_update=compare_versions(release.version, current_version) > 0,
        release=release,
    )
