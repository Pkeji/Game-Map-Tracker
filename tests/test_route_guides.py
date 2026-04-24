import json
import tempfile
import unittest
from pathlib import Path

from route_manager import (
    _GuideTarget,
    _distance_to_segment,
    _guide_distance_label,
    _guide_target_for_player,
    _load_teleport_points,
    _nearest_segment,
    _nearest_teleport_label,
    _nearest_unvisited_node,
)


class RouteGuideTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
