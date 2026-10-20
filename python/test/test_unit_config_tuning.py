import json
import sys
import unittest
from pathlib import Path

PYTHON_ROOT = Path(__file__).resolve().parents[1]
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from modes.city import config_city
from modes.race import config_race
from utils.json_config import validate_pulse_sequence


class ConfigTuningTests(unittest.TestCase):
    def test_default_sequences_are_valid_for_each_mode(self):
        city_sequences = (
            config_city.OBSTACLE_LANE_LEFT_SEQUENCE,
            config_city.OBSTACLE_LANE_RIGHT_SEQUENCE,
            config_city.CITY_CROSSWALK_TURN_RIGHT_SEQUENCE,
            config_city.CITY_CROSSWALK_TURN_LEFT_SEQUENCE,
            config_city.CITY_CROSSWALK_STRAIGHT_SEQUENCE,
        )
        race_sequences = (
            config_race.OBSTACLE_LANE_LEFT_SEQUENCE,
            config_race.OBSTACLE_LANE_RIGHT_SEQUENCE,
        )
        for sequence in city_sequences + race_sequences:
            self.assertEqual(validate_pulse_sequence("sequence", sequence), sequence)

    def test_sequence_whitespace_is_normalized_and_bad_commands_are_rejected(self):
        self.assertEqual(validate_pulse_sequence("seq", "  f 220 80 95  "), "f 220 80 95")
        for sequence in (
            "f 220 80", "left 220 80 95", "f 300 80 95",
            "b 200 0 90", "f 200 20 181", "f 200 many 95",
        ):
            with self.subTest(sequence=sequence):
                with self.assertRaises(ValueError):
                    validate_pulse_sequence("seq", sequence)

    def test_city_hardcodes_and_line_thresholds_are_json_backed(self):
        data = json.loads((PYTHON_ROOT / "city.json").read_text(encoding="utf-8"))
        expected = {
            "OBSTACLE_LANE_LEFT_SEQUENCE": config_city.OBSTACLE_LANE_LEFT_SEQUENCE,
            "OBSTACLE_LANE_RIGHT_SEQUENCE": config_city.OBSTACLE_LANE_RIGHT_SEQUENCE,
            "CITY_CROSSWALK_TURN_RIGHT_SEQUENCE": config_city.CITY_CROSSWALK_TURN_RIGHT_SEQUENCE,
            "CITY_CROSSWALK_TURN_LEFT_SEQUENCE": config_city.CITY_CROSSWALK_TURN_LEFT_SEQUENCE,
            "CITY_CROSSWALK_STRAIGHT_SEQUENCE": config_city.CITY_CROSSWALK_STRAIGHT_SEQUENCE,
            "CROSSWALK_VERTICAL_MIN_LINES": config_city.CROSSWALK_VERTICAL_MIN_LINES,
            "CROSSWALK_HORIZONTAL_MIN_LINES": config_city.CROSSWALK_HORIZONTAL_MIN_LINES,
            "USE_PID": config_city.USE_PID, "KP": config_city.KP, "KI": config_city.KI,
            "KD": config_city.KD, "KT": config_city.KT,
            "OUTPUT_LIMITS": list(config_city.OUTPUT_LIMITS),
            "AUTO_UPDATE_KP": config_city.AUTO_UPDATE_KP,
            "PID_MIN_DT": config_city.PID_MIN_DT, "PID_MAX_DT": config_city.PID_MAX_DT,
            "PID_DERIVATIVE_FILTER": config_city.PID_DERIVATIVE_FILTER,
        }
        for key, value in expected.items():
            with self.subTest(key=key):
                self.assertEqual(data[key], value)
        self.assertEqual(data["CROSSWALK_VERTICAL_MIN_LINES"], 6)
        self.assertEqual(data["CROSSWALK_HORIZONTAL_MIN_LINES"], 3)

    def test_race_keeps_distinct_obstacle_and_pid_defaults_without_city_routes(self):
        data = json.loads((PYTHON_ROOT / "race.json").read_text(encoding="utf-8"))
        self.assertEqual(data["OBSTACLE_LANE_LEFT_SEQUENCE"], config_race.OBSTACLE_LANE_LEFT_SEQUENCE)
        self.assertEqual(data["OBSTACLE_LANE_RIGHT_SEQUENCE"], config_race.OBSTACLE_LANE_RIGHT_SEQUENCE)
        self.assertEqual(data["KP"], config_race.KP)
        self.assertEqual(data["OUTPUT_LIMITS"], list(config_race.OUTPUT_LIMITS))
        self.assertNotIn("CITY_CROSSWALK_TURN_RIGHT_SEQUENCE", data)
        self.assertNotIn("CROSSWALK_VERTICAL_MIN_LINES", data)

    def test_city_pedestrian_routing_and_crosswalk_line_counts_use_config(self):
        city_source = (PYTHON_ROOT / "modes" / "city" / "city.py").read_text(encoding="utf-8")
        vision_source = (PYTHON_ROOT / "vision" / "city_vision_processing.py").read_text(encoding="utf-8")
        race_source = (PYTHON_ROOT / "modes" / "race" / "race.py").read_text(encoding="utf-8")
        template = (PYTHON_ROOT / "stream" / "templates" / "stream.html").read_text(encoding="utf-8")
        self.assertIn("config_city.CITY_CROSSWALK_TURN_RIGHT_SEQUENCE", city_source)
        self.assertIn("config_city.CITY_CROSSWALK_TURN_LEFT_SEQUENCE", city_source)
        self.assertIn("config_city.CITY_CROSSWALK_STRAIGHT_SEQUENCE", city_source)
        self.assertIn("conf.CROSSWALK_VERTICAL_MIN_LINES", vision_source)
        self.assertIn("conf.CROSSWALK_HORIZONTAL_MIN_LINES", vision_source)
        self.assertIn("config_race.OBSTACLE_LANE_LEFT_SEQUENCE", race_source)
        self.assertIn("{% if mode == 'city' %}", template)

        # City route cards are arranged like road directions: left, straight, right.
        heading = template.index("<h3>City · Pedestrian / Crosswalk Routes</h3>")
        grid_start = template.index('<div class="maneuver-grid">', heading)
        grid_end = template.index('<h3 style="margin-top:18px">Crosswalk Line-count Thresholds</h3>', grid_start)
        city_routes = template[grid_start:grid_end]
        self.assertLess(city_routes.index('id="maneuver_city_left"'), city_routes.index('id="maneuver_city_straight"'))
        self.assertLess(city_routes.index('id="maneuver_city_straight"'), city_routes.index('id="maneuver_city_right"'))

        self.assertNotIn('<span class="console-count" id="console_count">', template)
        self.assertIn('id="console_count_events"', template)
        self.assertIn('id="console_count_api"', template)
        self.assertIn('id="console_count_python"', template)
        stream_core = (PYTHON_ROOT / "stream" / "static" / "stream-core.js").read_text(encoding="utf-8")
        self.assertIn("function updateConsoleTabCounts()", stream_core)
        self.assertIn("count>99?'+99':String(count)", stream_core)


if __name__ == "__main__":
    unittest.main()
