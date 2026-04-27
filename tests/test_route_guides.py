import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from route_manager import (
    _GuideTarget,
    _distance_to_segment,
    _guide_distance_label,
    _guide_target_for_player,
    _load_teleport_points,
    _nearest_segment,
    _nearest_teleport_label,
    _nearest_unvisited_node,
    _route_color_from_hex,
    RouteManager,
)


class RouteGuideTests(unittest.TestCase):
    def test_route_color_uses_existing_multi_color_cache_when_enabled(self) -> None:
        manager = RouteManager.__new__(RouteManager)
        manager._color_cache = {"a": (1, 2, 3), "b": (4, 5, 6)}

        with patch("config.ROUTE_MULTI_COLOR_ENABLED", True):
            self.assertEqual(manager.color_for("a"), (1, 2, 3))
            self.assertEqual(manager.color_for("b"), (4, 5, 6))

    def test_route_color_uses_default_color_when_multi_color_disabled(self) -> None:
        manager = RouteManager.__new__(RouteManager)
        manager._color_cache = {"a": (1, 2, 3), "b": (4, 5, 6)}

        with patch("config.ROUTE_MULTI_COLOR_ENABLED", False), patch("config.ROUTE_DEFAULT_COLOR", "#1ad1ff"):
            self.assertEqual(manager.color_for("a"), (255, 209, 26))
            self.assertEqual(manager.color_for("b"), (255, 209, 26))

    def test_invalid_route_default_color_falls_back_to_blue(self) -> None:
        self.assertEqual(_route_color_from_hex("not-a-color"), (255, 209, 26))

    def test_distance_to_segment_projects_inside_segment(self) -> None:
        distance, projection = _distance_to_segment((5.0, 5.0), (0.0, 0.0), (10.0, 0.0))

        self.assertAlmostEqual(distance, 5.0)
        self.assertAlmostEqual(projection[0], 5.0)
        self.assertAlmostEqual(projection[1], 0.0)

    def test_nearest_unvisited_node_ignores_visited_points(self) -> None:
        routes = [
            {
                "points": [
                    {"x": 1, "y": 0, "visited": True},
                    {"x": 100, "y": 0, "visited": False},
                ],
            },
            {"points": [{"x": 12, "y": 9, "visited": False}]},
        ]

        result = _nearest_unvisited_node(routes, (0.0, 0.0))

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result[1], (12.0, 9.0))

    def test_segment_with_visited_start_targets_end_point(self) -> None:
        route = {
            "points": [
                {"x": 0, "y": 0, "visited": True},
                {"x": 100, "y": 0, "visited": False},
            ],
        }

        target = _guide_target_for_player([route], (50.0, 5.0), 80.0, 10.0)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (100.0, 0.0))

    def test_unvisited_segment_targets_nearest_unvisited_node(self) -> None:
        route = {
            "points": [
                {"x": 0, "y": 0, "visited": False},
                {"x": 100, "y": 0, "visited": False},
            ],
        }

        target = _guide_target_for_player([route], (5.0, 4.0), 80.0, 10.0)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (0.0, 0.0))

    def test_visited_segment_end_falls_back_to_nearest_unvisited_node(self) -> None:
        routes = [
            {
                "points": [
                    {"x": 0, "y": 0, "visited": True},
                    {"x": 100, "y": 0, "visited": True},
                    {"x": 200, "y": 0, "visited": False},
                ],
            },
        ]

        target = _guide_target_for_player(routes, (50.0, 5.0), 80.0, 10.0)

        self.assertIsNotNone(target)
        assert target is not None
        self.assertEqual(target.xy, (200.0, 0.0))

    def test_nearest_segment_includes_loop_closing_segment(self) -> None:
        route = {
            "loop": True,
            "points": [
                {"x": 0, "y": 0},
                {"x": 100, "y": 0},
                {"x": 0, "y": 100},
            ],
        }

        result = _nearest_segment([route], (4.0, 50.0), 10.0)

        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result[2], 2)
        self.assertEqual(result[3], 0)

    def test_distance_label_hidden_when_target_is_visible(self) -> None:
        target = _GuideTarget((75.0, 50.0), 75.0)

        label = _guide_distance_label(target, vx1=0, vy1=0, width=100, height=100)

        self.assertIsNone(label)

    def test_edges_route_uses_nodes_as_runtime_points_without_writing_source(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            routes_dir = Path(tmp) / "routes"
            category = routes_dir / "其他"
            category.mkdir(parents=True)
            source = category / "edge-route.json"
            payload = {
                "name": "edge-route",
                "points": [{"x": 999, "y": 999, "label": "legacy"}],
                "nodes": [
                    {"id": "a", "x": 10, "y": 20, "node_type": "collect"},
                    {"id": "b", "x": 30, "y": 40, "node_type": "virtual"},
                ],
                "edges": [
                    {"id": "e1", "from": "a", "to": "b", "edge_type": "virtual"},
                ],
            }
            source.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
            before = source.read_text(encoding="utf-8")

            manager = RouteManager(str(routes_dir))
            route = next(route for _category, route in manager.iter_routes() if route.get("display_name") == "edge-route")

            self.assertEqual(source.read_text(encoding="utf-8"), before)
            self.assertEqual([(point["x"], point["y"], point["node_type"]) for point in route["points"]], [
                (10, 20, "collect"),
                (30, 40, "virtual"),
            ])

            route_id = manager.route_id(route)
            self.assertTrue(manager.set_point_annotation(route_id, 1, "ore", "矿石"))
            saved = json.loads(source.read_text(encoding="utf-8"))
            self.assertEqual(saved["points"], payload["points"])
            self.assertEqual(saved["nodes"][1]["typeId"], "ore")
            self.assertEqual(saved["nodes"][1]["type"], "矿石")

    def test_edges_route_without_points_writes_node_edits_to_nodes_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            routes_dir = Path(tmp) / "routes"
            category = routes_dir / "其他"
            category.mkdir(parents=True)
            source = category / "edge-route.json"
            source.write_text(
                json.dumps(
                    {
                        "name": "edge-route",
                        "nodes": [
                            {"id": "a", "x": 10, "y": 20},
                            {"id": "b", "x": 30, "y": 40},
                        ],
                        "edges": [
                            {"id": "e1", "from": "a", "to": "b", "edge_type": "normal"},
                        ],
                    },
                    indent=2,
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            manager = RouteManager(str(routes_dir))
            route = next(route for _category, route in manager.iter_routes() if route.get("display_name") == "edge-route")
            route_id = manager.route_id(route)

            self.assertTrue(manager.set_point_annotation(route_id, 0, "ore", "矿石"))
            saved = json.loads(source.read_text(encoding="utf-8"))
            self.assertNotIn("points", saved)
            self.assertEqual(saved["nodes"][0]["typeId"], "ore")
            self.assertEqual(saved["nodes"][0]["type"], "矿石")

    def test_distance_label_shown_when_target_is_outside_crop(self) -> None:
        target = _GuideTarget((180.0, 50.0), 180.2)

        label = _guide_distance_label(target, vx1=0, vy1=0, width=100, height=100)

        self.assertEqual(label, "180px")

    def test_distance_label_uses_map_coordinate_distance(self) -> None:
        target = _GuideTarget((250.0, 120.0), 130.6)

        label = _guide_distance_label(target, vx1=200, vy1=100, width=40, height=40)

        self.assertEqual(label, "131px")

    def test_distance_label_hidden_without_target(self) -> None:
        label = _guide_distance_label(None, vx1=0, vy1=0, width=100, height=100)

        self.assertIsNone(label)

    def test_load_teleport_points_from_route_json_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "a.json").write_text(
                json.dumps(
                    {
                        "name": "传送",
                        "points": [
                            {"x": 10, "y": 20, "label": "港口"},
                            {"x": 30, "y": 40, "label": "农庄"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )

            points = _load_teleport_points(folder)

        self.assertEqual(len(points), 2)
        self.assertEqual(points[0].xy, (10.0, 20.0))
        self.assertEqual(points[0].label, "港口")
        self.assertEqual(points[1].label, "农庄")

    def test_nearest_teleport_label_uses_target_point(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "a.json").write_text(
                json.dumps(
                    {
                        "points": [
                            {"x": 0, "y": 0, "label": "远处"},
                            {"x": 95, "y": 105, "label": "最近传送点"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            points = _load_teleport_points(folder)

        label = _nearest_teleport_label(points, (100.0, 100.0))

        self.assertEqual(label, "最近传送点")

    def test_load_teleport_points_tolerates_missing_invalid_and_empty_data(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / "bad.json").write_text("{not json", encoding="utf-8")
            (folder / "empty.json").write_text(
                json.dumps({"points": []}),
                encoding="utf-8",
            )
            (folder / "partial.json").write_text(
                json.dumps({"points": [{"x": 1}, {"x": "bad", "y": 2}]}),
                encoding="utf-8",
            )

            points = _load_teleport_points(folder)

        self.assertEqual(points, [])
        self.assertEqual(_load_teleport_points(Path(tmp) / "missing"), [])
        self.assertIsNone(_nearest_teleport_label([], (0.0, 0.0)))

    def test_set_point_visited_updates_progress_without_rewriting_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [{"x": 1, "y": 2}, {"x": 3, "y": 4}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertFalse(manager.point_visited("2026010101", 1))
            self.assertTrue(manager.set_point_visited("2026010101", 1, True))
            self.assertTrue(manager.point_visited("2026010101", 1))
            progress = json.loads((base / "progress.json").read_text(encoding="utf-8"))
            self.assertEqual(progress, {"2026010101": [1]})
            route_payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertNotIn("visited", route_payload["points"][1])

            self.assertTrue(manager.set_point_visited("2026010101", 1, False))
            self.assertFalse(manager.point_visited("2026010101", 1))
            self.assertEqual(json.loads((base / "progress.json").read_text(encoding="utf-8")), {})

    def test_point_visited_rejects_invalid_route_or_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            (category / "路线.json").write_text(
                json.dumps({"id": "2026010101", "name": "路线", "points": [{"x": 1, "y": 2}]}),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertIsNone(manager.point_visited("missing", 0))
            self.assertIsNone(manager.point_visited("2026010101", 9))
            self.assertFalse(manager.set_point_visited("missing", 0, True))
            self.assertFalse(manager.set_point_visited("2026010101", 9, True))

    def test_route_point_annotation_detection_accepts_type_or_type_id(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            (category / "路线.json").write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [
                            {"x": 1, "y": 2},
                            {"x": 3, "y": 4, "typeId": "flower"},
                            {"x": 5, "y": 6, "type": "矿石"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertFalse(manager.route_point_has_annotation("2026010101", 0))
            self.assertTrue(manager.route_point_has_annotation("2026010101", 1))
            self.assertTrue(manager.route_point_has_annotation("2026010101", 2))
            self.assertFalse(manager.route_point_has_annotation("2026010101", 9))

    def test_set_point_annotation_writes_type_fields_to_route_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [{"x": 1, "y": 2, "visited": True}],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.set_point_annotation("2026010101", 0, "flower", "向阳花"))
            self.assertTrue(manager.route_point_has_annotation("2026010101", 0))
            self.assertEqual(manager.route_point_annotation_type_id("2026010101", 0), "flower")
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["points"][0]["typeId"], "flower")
            self.assertEqual(payload["points"][0]["type"], "向阳花")
            self.assertNotIn("visited", payload["points"][0])

    def test_set_point_annotation_rejects_invalid_inputs_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {"id": "2026010101", "name": "路线", "points": [{"x": 1, "y": 2}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            before = route_file.read_text(encoding="utf-8")
            manager = RouteManager(str(base))

            self.assertFalse(manager.set_point_annotation("missing", 0, "flower", "向阳花"))
            self.assertFalse(manager.set_point_annotation("2026010101", 9, "flower", "向阳花"))
            self.assertFalse(manager.set_point_annotation("2026010101", 0, "", "向阳花"))
            self.assertEqual(route_file.read_text(encoding="utf-8"), before)

    def test_clear_point_annotation_removes_type_fields_only(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [
                            {
                                "x": 1,
                                "y": 2,
                                "label": "节点",
                                "radius": 30,
                                "typeId": "flower",
                                "type": "向阳花",
                                "visited": True,
                            }
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.clear_point_annotation("2026010101", 0))
            self.assertFalse(manager.route_point_has_annotation("2026010101", 0))
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            point = payload["points"][0]
            self.assertNotIn("typeId", point)
            self.assertNotIn("type", point)
            self.assertEqual(point["label"], "节点")
            self.assertEqual(point["radius"], 30)
            self.assertNotIn("visited", point)

    def test_clear_point_annotation_handles_partial_annotations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {
                        "id": "2026010101",
                        "name": "路线",
                        "points": [
                            {"x": 1, "y": 2, "typeId": "flower"},
                            {"x": 3, "y": 4, "type": "矿石"},
                        ],
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            self.assertTrue(manager.clear_point_annotation("2026010101", 0))
            self.assertTrue(manager.clear_point_annotation("2026010101", 1))
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            self.assertNotIn("typeId", payload["points"][0])
            self.assertNotIn("type", payload["points"][0])
            self.assertNotIn("typeId", payload["points"][1])
            self.assertNotIn("type", payload["points"][1])

    def test_clear_point_annotation_rejects_invalid_inputs_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "采集"
            category.mkdir()
            route_file = category / "路线.json"
            route_file.write_text(
                json.dumps(
                    {"id": "2026010101", "name": "路线", "points": [{"x": 1, "y": 2, "typeId": "flower"}]},
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            before = route_file.read_text(encoding="utf-8")
            manager = RouteManager(str(base))

            self.assertFalse(manager.clear_point_annotation("missing", 0))
            self.assertFalse(manager.clear_point_annotation("2026010101", 9))
            self.assertEqual(route_file.read_text(encoding="utf-8"), before)

    def test_add_annotation_point_appends_point_and_updates_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [
                            {
                                "typeId": "flower",
                                "type": "Sunflower",
                                "group": "Collect",
                                "groupId": "1",
                                "count": 1,
                            }
                        ],
                        "pointsByType": {
                            "flower": [{"x": 1, "y": 2, "label": "old", "type": "Sunflower", "typeId": "flower"}]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager._annotation_points_cache = {"flower": []}

            with patch("route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertTrue(manager.add_annotation_point(10, 20, "flower", "Sunflower"))

            payload = json.loads(points_file.read_text(encoding="utf-8"))
            points = payload["pointsByType"]["flower"]
            self.assertEqual(len(points), 2)
            self.assertEqual(payload["types"][0]["count"], 2)
            self.assertEqual(points[-1]["x"], 10)
            self.assertEqual(points[-1]["y"], 20)
            self.assertEqual(points[-1]["label"], "Sunflower")
            self.assertEqual(points[-1]["type"], "Sunflower")
            self.assertEqual(points[-1]["typeId"], "flower")
            self.assertTrue(points[-1]["manual"])
            self.assertIsNone(manager._annotation_points_cache)

    def test_add_annotation_point_creates_missing_points_bucket_for_known_type(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "ore", "type": "Ore", "group": "Ore", "count": 0}],
                        "pointsByType": {},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))

            with patch("route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertTrue(manager.add_annotation_point(3, 4, "ore", "Ore"))

            payload = json.loads(points_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["types"][0]["count"], 1)
            self.assertEqual(payload["pointsByType"]["ore"][0]["typeId"], "ore")

    def test_add_annotation_point_rejects_invalid_type_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "Sunflower", "count": 0}],
                        "pointsByType": {"flower": []},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            before = points_file.read_text(encoding="utf-8")
            manager = RouteManager(str(Path(tmp) / "routes"))

            with patch("route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertFalse(manager.add_annotation_point(10, 20, "", "Sunflower"))
                self.assertFalse(manager.add_annotation_point(10, 20, "missing", "Missing"))
            self.assertEqual(points_file.read_text(encoding="utf-8"), before)

    def test_add_annotation_point_rejects_missing_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RouteManager(str(Path(tmp) / "routes"))
            missing_file = Path(tmp) / "missing.json"

            with patch("route_manager._default_annotation_points_file", return_value=str(missing_file)):
                self.assertFalse(manager.add_annotation_point(10, 20, "flower", "Sunflower"))

    def test_hit_test_annotation_point_returns_raw_points_index(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "Sunflower", "count": 2}],
                        "pointsByType": {
                            "flower": [
                                {"x": "bad", "y": 2},
                                {"x": 100, "y": 100, "typeId": "flower"},
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager.set_annotation_type_ids(["flower"])

            with patch("route_manager._default_annotation_points_file", return_value=str(points_file)):
                hit = manager.hit_test_annotation_point(102, 101, 5)

            self.assertIsNotNone(hit)
            self.assertEqual(hit["typeId"], "flower")
            self.assertEqual(hit["pointIndex"], 1)

    def test_change_annotation_point_type_moves_point_and_updates_counts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [
                            {"typeId": "flower", "type": "Sunflower", "count": 1},
                            {"typeId": "ore", "type": "Ore", "count": 0},
                        ],
                        "pointsByType": {
                            "flower": [{"x": 1, "y": 2, "label": "Keep Label", "sourceId": 7}],
                            "ore": [],
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager._annotation_points_cache = {"flower": []}

            with patch("route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertTrue(manager.change_annotation_point_type("flower", 0, "ore", "Ore"))

            payload = json.loads(points_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["types"][0]["count"], 0)
            self.assertEqual(payload["types"][1]["count"], 1)
            self.assertEqual(payload["pointsByType"]["flower"], [])
            moved = payload["pointsByType"]["ore"][0]
            self.assertEqual(moved["x"], 1)
            self.assertEqual(moved["y"], 2)
            self.assertEqual(moved["label"], "Keep Label")
            self.assertEqual(moved["sourceId"], 7)
            self.assertEqual(moved["typeId"], "ore")
            self.assertEqual(moved["type"], "Ore")
            self.assertIsNone(manager._annotation_points_cache)

    def test_delete_annotation_point_removes_point_and_updates_count(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "Sunflower", "count": 2}],
                        "pointsByType": {
                            "flower": [
                                {"x": 1, "y": 2, "label": "A"},
                                {"x": 3, "y": 4, "label": "B"},
                            ]
                        },
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            manager = RouteManager(str(Path(tmp) / "routes"))

            with patch("route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertTrue(manager.delete_annotation_point("flower", 0))

            payload = json.loads(points_file.read_text(encoding="utf-8"))
            self.assertEqual(payload["types"][0]["count"], 1)
            self.assertEqual(len(payload["pointsByType"]["flower"]), 1)
            self.assertEqual(payload["pointsByType"]["flower"][0]["label"], "B")

    def test_insert_annotation_point_into_route_preserves_type_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            category = base / "routes"
            category.mkdir()
            route_file = category / "route.json"
            route_file.write_text(
                json.dumps({"id": "2026010101", "name": "route", "points": []}, ensure_ascii=False),
                encoding="utf-8",
            )
            manager = RouteManager(str(base))

            outcomes = manager.insert_point_into_routes(
                10,
                20,
                ["2026010101"],
                point_fields={"typeId": "flower", "type": "Sunflower", "label": "Field Flower", "visited": True},
            )

            self.assertEqual(outcomes["2026010101"], 0)
            payload = json.loads(route_file.read_text(encoding="utf-8"))
            point = payload["points"][0]
            self.assertEqual(point["x"], 10)
            self.assertEqual(point["y"], 20)
            self.assertEqual(point["typeId"], "flower")
            self.assertEqual(point["type"], "Sunflower")
            self.assertEqual(point["label"], "Field Flower")
            self.assertNotIn("visited", point)

    def test_annotation_point_mutations_reject_invalid_inputs_without_writing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            points_file = Path(tmp) / "points.json"
            points_file.write_text(
                json.dumps(
                    {
                        "types": [{"typeId": "flower", "type": "Sunflower", "count": 1}],
                        "pointsByType": {"flower": [{"x": 1, "y": 2}]},
                    },
                    ensure_ascii=False,
                ),
                encoding="utf-8",
            )
            before = points_file.read_text(encoding="utf-8")
            manager = RouteManager(str(Path(tmp) / "routes"))

            with patch("route_manager._default_annotation_points_file", return_value=str(points_file)):
                self.assertFalse(manager.change_annotation_point_type("flower", 2, "flower", "Sunflower"))
                self.assertFalse(manager.change_annotation_point_type("flower", 0, "missing", "Missing"))
                self.assertFalse(manager.delete_annotation_point("flower", 2))
                self.assertIsNone(manager.annotation_point("flower", 2))
            self.assertEqual(points_file.read_text(encoding="utf-8"), before)

    def test_create_optimized_annotation_route_writes_algorithm_route(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager._annotation_points_cache = {
                "flower": [
                    {"x": 100, "y": 100, "label": "花 A", "radius": 30, "typeId": "flower"},
                    {"x": 150, "y": 100, "label": "花 B", "radius": 30, "typeId": "flower"},
                    {"x": 120, "y": 140, "label": "花 C", "radius": 30, "typeId": "flower"},
                ]
            }

            result = manager.create_optimized_annotation_route("flower", "向阳花")
            route_path = Path(result["path"])
            payload = json.loads(route_path.read_text(encoding="utf-8"))

            self.assertEqual(route_path.name, "向阳花_路线(算法生成).json")
            self.assertEqual(route_path.parent.name, "算法生成")
            self.assertEqual(payload["name"], "向阳花_路线(算法生成)")
            self.assertFalse(payload["loop"])
            self.assertEqual(len(payload["points"]), 3)
            self.assertTrue(all(point["typeId"] == "flower" for point in payload["points"]))
            self.assertTrue(all(point["radius"] == 30 for point in payload["points"]))
            self.assertIn("来源标注：向阳花", payload["notes"])
            self.assertIn(result["id"], manager._route_index_by_id)

    def test_create_optimized_annotation_route_auto_numbers_duplicates(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager._annotation_points_cache = {
                "ore": [
                    {"x": 0, "y": 0, "typeId": "ore"},
                    {"x": 10, "y": 0, "typeId": "ore"},
                ]
            }

            first = manager.create_optimized_annotation_route("ore", "矿石")
            second = manager.create_optimized_annotation_route("ore", "矿石")

            self.assertEqual(Path(first["path"]).name, "矿石_路线(算法生成).json")
            self.assertEqual(Path(second["path"]).name, "矿石_路线(算法生成) 2.json")
            self.assertTrue(Path(first["path"]).exists())
            self.assertTrue(Path(second["path"]).exists())
            self.assertNotEqual(first["id"], second["id"])

    def test_create_optimized_annotation_route_rejects_empty_points(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            manager = RouteManager(str(Path(tmp) / "routes"))
            manager._annotation_points_cache = {"empty": [{"x": "bad", "y": 1}]}

            with self.assertRaises(ValueError):
                manager.create_optimized_annotation_route("empty", "空标注")

            generated = Path(tmp) / "routes" / "算法生成"
            self.assertFalse(generated.exists())


if __name__ == "__main__":
    unittest.main()
