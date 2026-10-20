import math
import unittest

from tools.benchmark_multiprocessing import parse_performance_line, summarize_values


class MultiprocessingBenchmarkParsingTests(unittest.TestCase):
    def test_parses_numeric_performance_metrics(self):
        parsed = parse_performance_line(
            "performance: fps=29.5 loop_mean=30.0ms loop_p95=35.2ms loop_p99=45.0ms"
        )
        self.assertEqual(parsed["fps"], 29.5)
        self.assertEqual(parsed["loop_mean"], "30.0ms")

    def test_parses_stage_and_string_source_values(self):
        parsed = parse_performance_line(
            "performance sources: camera_fps=58.0 sign_worker=process sign_alive=True sign_queue=0"
        )
        self.assertEqual(parsed["camera_fps"], 58.0)
        self.assertEqual(parsed["sign_worker"], "process")
        self.assertEqual(parsed["sign_alive"], "True")
        self.assertEqual(parsed["sign_queue"], 0.0)

    def test_ignores_non_performance_lines(self):
        self.assertEqual(parse_performance_line("INFO camera initialized"), {})

    def test_nearest_rank_summary_handles_tail_latency(self):
        result = summarize_values(list(range(1, 101)))
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result["median"], 50.5)
        self.assertEqual(result["p95"], 95)
        self.assertEqual(result["max"], 100)

    def test_empty_and_nonfinite_samples_are_safe(self):
        self.assertIsNone(summarize_values([]))
        self.assertEqual(summarize_values([1.0, float("nan"), 3.0])["count"], 2)


if __name__ == "__main__":
    unittest.main()
