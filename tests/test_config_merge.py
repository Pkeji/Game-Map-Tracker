import json
import tempfile
import unittest
from pathlib import Path

import config


class ConfigMergeTests(unittest.TestCase):
    def test_merge_adds_new_fields_and_preserves_user_values(self) -> None:
        defaults = {
            "CONFIG_VERSION": 2,
            "WINDOW_GEOMETRY": {"x": 0, "y": 0, "width": 420, "height": 360},
            "SIDEBAR_WIDTH": 270,
            "NESTED": {"old": 1, "new": 2},
        }
        user = {
            "CONFIG_VERSION": 1,
            "WINDOW_GEOMETRY": {"x": 99, "y": 88},
            "SIDEBAR_WIDTH": 333,
            "NESTED": {"old": 9},
            "LEGACY_KEY": "keep me",
        }

        merged, repaired = config.merge_config_payload(defaults, user)

        self.assertEqual(repaired, [])
        self.assertEqual(merged["CONFIG_VERSION"], 2)
        self.assertEqual(merged["WINDOW_GEOMETRY"], {"x": 99, "y": 88, "width": 420, "height": 360})
        self.assertEqual(merged["SIDEBAR_WIDTH"], 333)
        self.assertEqual(merged["NESTED"], {"old": 9, "new": 2})
        self.assertEqual(merged["LEGACY_KEY"], "keep me")

    def test_merge_repairs_obviously_wrong_types(self) -> None:
        defaults = {
            "CONFIG_VERSION": 2,
            "SIDEBAR_COLLAPSED": True,
            "SIDEBAR_WIDTH": 270,
            "SIFT_CLAHE_LIMIT": 3.0,
            "MINIMAP": {},
        }
        user = {
            "CONFIG_VERSION": "old",
            "SIDEBAR_COLLAPSED": "yes",
            "SIDEBAR_WIDTH": "wide",
            "SIFT_CLAHE_LIMIT": 2,
            "MINIMAP": [],
        }

        merged, repaired = config.merge_config_payload(defaults, user)

        self.assertEqual(merged["CONFIG_VERSION"], 2)
        self.assertEqual(merged["SIDEBAR_COLLAPSED"], True)
        self.assertEqual(merged["SIDEBAR_WIDTH"], 270)
        self.assertEqual(merged["SIFT_CLAHE_LIMIT"], 2)
        self.assertEqual(merged["MINIMAP"], {})
        self.assertIn("SIDEBAR_COLLAPSED", repaired)
        self.assertIn("SIDEBAR_WIDTH", repaired)
        self.assertIn("MINIMAP", repaired)

    def test_merge_config_file_backs_up_and_rewrites_corrupt_json(self) -> None:
        defaults = {"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 270}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text("{broken", encoding="utf-8")

            merged = config.merge_config_file(str(path), defaults)

            self.assertEqual(merged, defaults)
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), defaults)
            self.assertEqual((Path(str(path) + ".bak")).read_text(encoding="utf-8"), "{broken")

    def test_merge_config_file_backs_up_before_writing_merged_config(self) -> None:
        defaults = {"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 270, "VIEW_SIZE": 400}
        user = {"SIDEBAR_WIDTH": 333}
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(json.dumps(user), encoding="utf-8")

            merged = config.merge_config_file(str(path), defaults)

            self.assertEqual(merged, {"CONFIG_VERSION": 2, "SIDEBAR_WIDTH": 333, "VIEW_SIZE": 400})
            self.assertEqual(json.loads(path.read_text(encoding="utf-8")), merged)
            self.assertEqual(json.loads((Path(str(path) + ".bak")).read_text(encoding="utf-8")), user)


if __name__ == "__main__":
    unittest.main()
