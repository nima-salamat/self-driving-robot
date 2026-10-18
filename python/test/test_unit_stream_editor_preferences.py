import unittest
from stream import WebStreamer

class StreamEditorPreferenceTests(unittest.TestCase):
    def setUp(self):
        self.streamer = WebStreamer.__new__(WebStreamer)

    def test_workspace_accepts_grid_and_roi_appearance_preferences(self):
        clean = self.streamer._sanitize_workspace({
            "view": {"grid": True, "gridMode": "dots", "gridSpacing": 0.05, "gridOpacity": 0.4, "gridThickness": 1.5, "gridDotSize": 2.5, "snap": True},
            "roiAppearance": {"labelFontSize": 16, "labelFontWeight": "600", "outlineThickness": 2.5, "handleSize": 12},
        })
        self.assertEqual(clean["view"]["gridMode"], "dots")
        self.assertEqual(clean["view"]["gridSpacing"], 0.05)
        self.assertTrue(clean["view"]["snap"])
        self.assertEqual(clean["roiAppearance"]["labelFontWeight"], "600")
        self.assertEqual(clean["roiAppearance"]["handleSize"], 12.0)

    def test_old_workspace_without_appearance_settings_remains_valid(self):
        clean = self.streamer._sanitize_workspace({"view": {"zoom": 1.0}})
        self.assertEqual(clean["roiAppearance"], {})
        self.assertEqual(clean["view"]["zoom"], 1.0)

    def test_invalid_grid_mode_and_out_of_range_appearance_are_rejected(self):
        with self.assertRaises(ValueError):
            self.streamer._sanitize_workspace({"view": {"gridMode": "triangles"}})
        with self.assertRaises(ValueError):
            self.streamer._sanitize_workspace({"roiAppearance": {"handleSize": 80}})

if __name__ == "__main__":
    unittest.main()
