import hashlib
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import config
import updater_main
from ui_island.services import app_updater


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


class AppUpdaterTests(unittest.TestCase):
    def setUp(self) -> None:
        self._old_base_dir = config.BASE_DIR
        self._old_config_file = config.CONFIG_FILE
        self._old_localappdata = os.environ.get("LOCALAPPDATA")

    def tearDown(self) -> None:
        config.BASE_DIR = self._old_base_dir
        config.CONFIG_FILE = self._old_config_file
        if self._old_localappdata is None:
            os.environ.pop("LOCALAPPDATA", None)
        else:
            os.environ["LOCALAPPDATA"] = self._old_localappdata

    def test_parse_manifest_rejects_unsafe_paths(self) -> None:
        payload = {
            "version": "0.2.0",
            "files": [
                {
                    "path": "../evil.exe",
                    "url": "https://example.test/evil.exe",
                    "sha256": "0" * 64,
                    "size": 1,
                }
            ],
        }

        with self.assertRaises(app_updater.ManifestError):
            app_updater.parse_app_manifest(payload)

    def test_build_update_plan_detects_restart_file(self) -> None:
        exe_payload = b"new exe"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "GMT-N.exe",
                        "url": "https://example.test/GMT-N.exe",
                        "sha256": _sha256_bytes(exe_payload),
                        "size": len(exe_payload),
                    }
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            Path(tmp, "GMT-N.exe").write_bytes(b"old exe")

            result = app_updater.build_update_plan(manifest, current_version="0.1.0")

        self.assertTrue(result.ok)
        self.assertTrue(result.has_update)
        self.assertTrue(result.requires_restart)
        self.assertEqual(result.changed_files[0].file.path, "GMT-N.exe")

    def test_build_update_plan_protects_user_modified_file_with_known_hash(self) -> None:
        old_payload = b"old route"
        new_payload = b"new route"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "routes/demo.json",
                        "url": "https://example.test/routes/demo.json",
                        "sha256": _sha256_bytes(new_payload),
                        "size": len(new_payload),
                    }
                ],
            }
        )
        installed = {"files": {"routes/demo.json": {"sha256": _sha256_bytes(old_payload)}}}

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            route = Path(tmp, "routes", "demo.json")
            route.parent.mkdir(parents=True)
            route.write_bytes(b"user edited")

            result = app_updater.build_update_plan(
                manifest,
                current_version="0.1.0",
                installed_manifest=installed,
            )

        self.assertTrue(result.ok)
        self.assertEqual(result.changed_files, ())
        self.assertEqual(result.skipped_conflicts, ("routes/demo.json",))

    def test_install_config_update_merges_without_overwriting_user_values(self) -> None:
        defaults = {
            "CONFIG_VERSION": 3,
            "SIDEBAR_WIDTH": 270,
            "VIEW_SIZE": 500,
            "WINDOW_GEOMETRY": {"x": 0, "y": 0, "width": 420, "height": 360},
        }
        defaults_bytes = json.dumps(defaults, ensure_ascii=False).encode("utf-8")
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "config.json",
                        "url": "https://example.test/config.json",
                        "sha256": _sha256_bytes(defaults_bytes),
                        "size": len(defaults_bytes),
                        "install": "merge_config",
                    }
                ],
            }
        )
        plan = app_updater.build_update_plan(manifest, current_version="0.1.0", installed_manifest={})

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            config.CONFIG_FILE = str(Path(tmp, "config.json"))
            Path(config.CONFIG_FILE).write_text(
                json.dumps({"SIDEBAR_WIDTH": 333, "WINDOW_GEOMETRY": {"x": 9, "y": 8}}, ensure_ascii=False),
                encoding="utf-8",
            )
            staging = Path(tmp, "staging")
            staging.mkdir()
            Path(staging, "config.json").write_text(json.dumps(defaults, ensure_ascii=False), encoding="utf-8")

            result = app_updater.install_non_restart_update(plan, staging)
            merged = json.loads(Path(config.CONFIG_FILE).read_text(encoding="utf-8"))

        self.assertTrue(result.ok)
        self.assertEqual(merged["CONFIG_VERSION"], 3)
        self.assertEqual(merged["SIDEBAR_WIDTH"], 333)
        self.assertEqual(merged["VIEW_SIZE"], 500)
        self.assertEqual(merged["WINDOW_GEOMETRY"], {"x": 9, "y": 8, "width": 420, "height": 360})

    def test_write_restart_update_job_contains_changed_files_and_manifest(self) -> None:
        payload = b"new exe"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "GMT-N.exe",
                        "url": "https://example.test/GMT-N.exe",
                        "sha256": _sha256_bytes(payload),
                        "size": len(payload),
                    }
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            Path(tmp, "GMT-N.exe").write_bytes(b"old exe")
            staging = Path(tmp, "staging")
            staging.mkdir()
            plan = app_updater.build_update_plan(manifest, current_version="0.1.0")

            job_path = app_updater.write_restart_update_job(plan, staging)
            job = json.loads(job_path.read_text(encoding="utf-8"))

        self.assertEqual(job["version"], "0.2.0")
        self.assertEqual(job["files"][0]["path"], "GMT-N.exe")
        self.assertEqual(job["manifest"]["files"][0]["sha256"], _sha256_bytes(payload))
        self.assertEqual(job["delete"], [])

    def test_start_restart_update_reports_missing_updater(self) -> None:
        payload = b"new exe"
        manifest = app_updater.parse_app_manifest(
            {
                "version": "0.2.0",
                "files": [
                    {
                        "path": "GMT-N.exe",
                        "url": "https://example.test/GMT-N.exe",
                        "sha256": _sha256_bytes(payload),
                        "size": len(payload),
                    }
                ],
            }
        )

        with tempfile.TemporaryDirectory() as tmp:
            config.BASE_DIR = tmp
            Path(tmp, "GMT-N.exe").write_bytes(b"old exe")
            staging = Path(tmp, "staging")
            staging.mkdir()
            plan = app_updater.build_update_plan(manifest, current_version="0.1.0")

            result = app_updater.start_restart_update(plan, staging, parent_pid=0)

        self.assertFalse(result.ok)
        self.assertTrue(result.requires_restart)
        self.assertIn("未找到更新器", result.error)

    def test_updater_installs_regular_file_and_writes_installed_manifest(self) -> None:
        new_payload = b"new file"
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOCALAPPDATA"] = str(Path(tmp) / "local")
            app_dir = Path(tmp, "app")
            staging = Path(tmp, "staging")
            app_dir.mkdir()
            staging.mkdir()
            Path(app_dir, "demo.txt").write_bytes(b"old file")
            Path(staging, "demo.txt").write_bytes(new_payload)
            job_path = Path(tmp, "job.json")
            job_path.write_text(
                json.dumps(
                    {
                        "version": "0.2.0",
                        "app_dir": str(app_dir),
                        "staging_dir": str(staging),
                        "exe_path": str(app_dir / "GMT-N.exe"),
                        "files": [
                            {
                                "path": "demo.txt",
                                "sha256": _sha256_bytes(new_payload),
                                "install": "copy",
                            }
                        ],
                        "delete": [],
                        "manifest": {
                            "version": "0.2.0",
                            "files": [
                                {
                                    "path": "demo.txt",
                                    "sha256": _sha256_bytes(new_payload),
                                    "size": len(new_payload),
                                    "install": "copy",
                                }
                            ],
                        },
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(updater_main.install_update_job(job_path))
            installed_manifest = json.loads(Path(app_dir, "installed-manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(Path(app_dir, "demo.txt").read_bytes(), new_payload)
            self.assertEqual(installed_manifest["version"], "0.2.0")
            self.assertEqual(installed_manifest["files"]["demo.txt"]["sha256"], _sha256_bytes(new_payload))

    def test_updater_merges_config_without_overwriting_user_values(self) -> None:
        defaults = {"CONFIG_VERSION": 5, "SIDEBAR_WIDTH": 270, "VIEW_SIZE": 600}
        defaults_bytes = json.dumps(defaults, ensure_ascii=False).encode("utf-8")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOCALAPPDATA"] = str(Path(tmp) / "local")
            app_dir = Path(tmp, "app")
            staging = Path(tmp, "staging")
            app_dir.mkdir()
            staging.mkdir()
            Path(app_dir, "config.json").write_text(json.dumps({"SIDEBAR_WIDTH": 333}), encoding="utf-8")
            Path(staging, "config.json").write_text(json.dumps(defaults, ensure_ascii=False), encoding="utf-8")
            job_path = Path(tmp, "job.json")
            job_path.write_text(
                json.dumps(
                    {
                        "version": "0.2.0",
                        "app_dir": str(app_dir),
                        "staging_dir": str(staging),
                        "exe_path": str(app_dir / "GMT-N.exe"),
                        "files": [
                            {
                                "path": "config.json",
                                "sha256": _sha256_bytes(defaults_bytes),
                                "install": "merge_config",
                            }
                        ],
                        "delete": [],
                        "manifest": {"version": "0.2.0", "files": []},
                    }
                ),
                encoding="utf-8",
            )

            self.assertTrue(updater_main.install_update_job(job_path))
            merged = json.loads(Path(app_dir, "config.json").read_text(encoding="utf-8"))

        self.assertEqual(merged["CONFIG_VERSION"], 5)
        self.assertEqual(merged["SIDEBAR_WIDTH"], 333)
        self.assertEqual(merged["VIEW_SIZE"], 600)

    def test_updater_rolls_back_when_replace_fails(self) -> None:
        new_payload = b"new file"
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LOCALAPPDATA"] = str(Path(tmp) / "local")
            app_dir = Path(tmp, "app")
            staging = Path(tmp, "staging")
            app_dir.mkdir()
            staging.mkdir()
            target = Path(app_dir, "demo.txt")
            target.write_bytes(b"old file")
            Path(staging, "demo.txt").write_bytes(new_payload)
            job_path = Path(tmp, "job.json")
            job_path.write_text(
                json.dumps(
                    {
                        "version": "0.2.0",
                        "app_dir": str(app_dir),
                        "staging_dir": str(staging),
                        "exe_path": str(app_dir / "GMT-N.exe"),
                        "files": [
                            {
                                "path": "demo.txt",
                                "sha256": _sha256_bytes(new_payload),
                                "install": "copy",
                            }
                        ],
                        "delete": [],
                        "manifest": {"version": "0.2.0", "files": []},
                    }
                ),
                encoding="utf-8",
            )

            with patch("updater_main.os.replace", side_effect=OSError("locked")):
                with self.assertRaises(OSError):
                    updater_main.install_update_job(job_path)

            self.assertEqual(target.read_bytes(), b"old file")


if __name__ == "__main__":
    unittest.main()
