"""Static contract tests for the opt-in Arduino command ACK envelope.

The host tests simulate serial ACK lines. Hardware compilation and actuator
behavior still require flashing/testing the matching firmware on the real board.
"""
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]


class ArduinoAckFirmwareContractTests(unittest.TestCase):
    def test_supported_firmware_variants_unwrap_only_explicit_ack_envelopes(self):
        for relative in ("arduino/main_nonBlocking.ino", "arduino/race_final_code.ino"):
            with self.subTest(firmware=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn("bool unwrapAckEnvelope(String &command, unsigned long &commandId)", source)
                self.assertIn("command.charAt(0) != '@'", source)
                self.assertIn('Serial.print("ACK ");', source)
                self.assertIn('Serial.println(" RECEIVED");', source)
                self.assertIn("bool ackRequested = unwrapAckEnvelope(work, ackCommandId);", source)
                self.assertIn("if (ackRequested) sendCommandAck(ackCommandId);", source)

    def test_firmware_serial_event_preserves_multiple_commands_as_separate_lines(self):
        for relative in ("arduino/main_nonBlocking.ino", "arduino/race_final_code.ino"):
            with self.subTest(firmware=relative):
                source = (ROOT / relative).read_text(encoding="utf-8")
                start = source.rindex("void serialEvent() {")
                end = source.index("\n}", start) + 2
                parser = source[start:end]
                self.assertIn("stringComplete = true;", parser)
                self.assertIn("break;", parser)
                self.assertIn("leave later lines in Serial's buffer", parser)

    def test_receipt_ack_is_documented_as_non_execution_confirmation(self):
        source = (ROOT / "python/arduino/arduino_connection.py").read_text(encoding="utf-8")
        self.assertIn("does not prove an actuator reached its target", source)
        self.assertIn('"acknowledged": acknowledged', source)


if __name__ == "__main__":
    unittest.main()
