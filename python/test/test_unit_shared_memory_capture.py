import threading
import time
import unittest
from types import SimpleNamespace

import numpy as np

from vision.shared_memory_capture import (
    SharedMemoryCapture,
    _CAPTURE_AT,
    _CAPTURE_MS,
    _FAILURES,
    _INITIALIZED,
    _MEASURED_FPS,
    _PI_MODE,
    _SEQ,
    _VALID,
)


class _AliveProcess:
    def is_alive(self):
        return True


class SharedMemoryCaptureReaderTests(unittest.TestCase):
    def make_reader(self, *, valid=True):
        capture = SharedMemoryCapture.__new__(SharedMemoryCapture)
        capture.frame_shape = (2, 3, 3)
        capture.resized_shape = (1, 2, 3)
        capture._raw_nbytes = int(np.prod(capture.frame_shape))
        capture._shared = SimpleNamespace(
            buf=bytearray(capture._raw_nbytes + int(np.prod(capture.resized_shape)))
        )
        capture._lock = threading.Lock()
        capture._frame_event = threading.Event()
        capture._process = _AliveProcess()
        capture._last_sequence = 0
        capture._metadata = [
            1.0, time.monotonic(), 24.0, 1.0 if valid else 0.0,
            0.0, 1.25, 0.0, 1.0, -1.0, -1.0,
        ]

        raw = np.ndarray(capture.frame_shape, dtype=np.uint8, buffer=capture._shared.buf)
        resized = np.ndarray(
            capture.resized_shape,
            dtype=np.uint8,
            buffer=capture._shared.buf,
            offset=capture._raw_nbytes,
        )
        raw[:] = np.arange(raw.size, dtype=np.uint8).reshape(raw.shape)
        resized[:] = 211
        return capture, raw.copy(), resized.copy()

    def test_reads_consistent_raw_and_resized_copies(self):
        capture, expected_raw, expected_resized = self.make_reader()

        raw, resized, state = capture.capture_frame(with_resize=True)

        np.testing.assert_array_equal(raw, expected_raw)
        np.testing.assert_array_equal(resized, expected_resized)
        self.assertTrue(state["valid"])
        self.assertEqual(state["sequence"], 1)
        self.assertFalse(np.shares_memory(raw, expected_raw))
        # Returned frames are stable even if the shared slot is reused later.
        np.ndarray(capture.frame_shape, dtype=np.uint8, buffer=capture._shared.buf)[:] = 0
        np.testing.assert_array_equal(raw, expected_raw)

    def test_raw_only_capture_does_not_copy_resized_slot(self):
        capture, expected_raw, _ = self.make_reader()

        raw, resized, state = capture.capture_frame(with_resize=False)

        np.testing.assert_array_equal(raw, expected_raw)
        self.assertIsNone(resized)
        self.assertTrue(state["valid"])

    def test_invalid_published_frame_is_returned_as_unavailable(self):
        capture, _, _ = self.make_reader(valid=False)

        raw, resized, state = capture.capture_frame(with_resize=True)

        self.assertIsNone(raw)
        self.assertIsNone(resized)
        self.assertFalse(state["valid"])
        self.assertEqual(capture._last_sequence, 1)


if __name__ == "__main__":
    unittest.main()
