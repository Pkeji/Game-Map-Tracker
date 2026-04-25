import unittest

import requests

from ui_island.services.update_checker import check_for_updates, compare_versions, normalize_version, parse_release


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None) -> None:
        self.status_code = status_code
        self._payload = payload or {}

    def json(self) -> dict:
        return self._payload


class _FakeSession:
    def __init__(self, response: _FakeResponse | None = None, exc: Exception | None = None) -> None:
        self.response = response
        self.exc = exc

    def get(self, *_args, **_kwargs):
        if self.exc is not None:
            raise self.exc
        return self.response


def _release(tag_name: str = "v1.2.3") -> dict:
    return {
        "tag_name": tag_name,
        "html_url": "https://github.com/Greenjiao/Game-Map-Tracker/releases/tag/v1.2.3",
        "name": "GMT-N v1.2.3",
        "body": "更新说明",
        "published_at": "2026-04-25T00:00:00Z",
        "assets": [
            {
                "name": "GMT-N-v1.2.3-windows.zip",
                "browser_download_url": "https://example.test/GMT-N.zip",
            }
        ],
    }


class UpdateCheckerTests(unittest.TestCase):
    def test_normalize_versions(self) -> None:
        self.assertEqual(normalize_version("v1.2.3"), "1.2.3")
        self.assertEqual(normalize_version("1.2.3"), "1.2.3")
        self.assertEqual(normalize_version("1.2.3-beta"), "1.2.3-beta")

    def test_compare_versions(self) -> None:
        self.assertGreater(compare_versions("v1.2.4", "1.2.3"), 0)
        self.assertEqual(compare_versions("v1.2.3", "1.2.3"), 0)
        self.assertLess(compare_versions("1.2.3-beta", "1.2.3"), 0)
        self.assertGreater(compare_versions("1.2.3-beta", "1.2.2"), 0)

    def test_parse_release_success(self) -> None:
        release = parse_release(_release("v1.2.3"))

        self.assertEqual(release.version, "1.2.3")
        self.assertEqual(release.name, "GMT-N v1.2.3")
        self.assertEqual(release.assets[0].name, "GMT-N-v1.2.3-windows.zip")

    def test_update_available(self) -> None:
        result = check_for_updates(
            current_version="0.1.0",
            session=_FakeSession(_FakeResponse(200, _release("v0.2.0"))),
        )

        self.assertTrue(result.ok)
        self.assertTrue(result.has_update)
        self.assertEqual(result.release.version, "0.2.0")

    def test_no_update_for_same_or_older_release(self) -> None:
        same = check_for_updates(
            current_version="0.2.0",
            session=_FakeSession(_FakeResponse(200, _release("v0.2.0"))),
        )
        older = check_for_updates(
            current_version="0.2.0",
            session=_FakeSession(_FakeResponse(200, _release("v0.1.9"))),
        )

        self.assertTrue(same.ok)
        self.assertFalse(same.has_update)
        self.assertTrue(older.ok)
        self.assertFalse(older.has_update)

    def test_network_error(self) -> None:
        result = check_for_updates(
            session=_FakeSession(exc=requests.ConnectionError("offline")),
        )

        self.assertFalse(result.ok)
        self.assertIn("无法连接 GitHub", result.error)

    def test_http_non_200(self) -> None:
        result = check_for_updates(session=_FakeSession(_FakeResponse(500)))

        self.assertFalse(result.ok)
        self.assertIn("HTTP 500", result.error)

    def test_empty_release(self) -> None:
        result = check_for_updates(session=_FakeSession(_FakeResponse(200, {})))

        self.assertFalse(result.ok)
        self.assertIn("响应为空", result.error)

    def test_missing_tag_name(self) -> None:
        result = check_for_updates(session=_FakeSession(_FakeResponse(200, {"name": "No tag"})))

        self.assertFalse(result.ok)
        self.assertIn("tag_name", result.error)


if __name__ == "__main__":
    unittest.main()
