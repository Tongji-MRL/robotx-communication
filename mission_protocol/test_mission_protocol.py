"""Unit tests for the isolated mission protocol codec."""

import unittest

from mission_protocol import decode_status, encode_status
from mission_protocol.command_code import COMMAND_CODES
from mission_protocol.error_code import ERROR_CODES


class MissionProtocolTests(unittest.TestCase):
    def test_encode_decode_round_trip(self):
        fields = {
            "vehicle": "TWAVE", "task": "TASK1", "progress": "READY",
            "error": "NONE", "command": "NONE",
        }
        self.assertEqual(encode_status(**fields), "10100000000000")
        self.assertEqual(decode_status(encode_status(**fields)), fields)

    def test_invalid_bit_length_is_rejected(self):
        for value in ("", "0" * 13, "0" * 15, "0" * 14 + "x"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                decode_status(value)

    def test_invalid_fields_are_rejected(self):
        fields = dict(vehicle="TWAVE", task="TASK1", progress="READY", error="NONE", command="NONE")
        for field in fields:
            invalid = fields | {field: "NOT_A_PROTOCOL_VALUE"}
            with self.subTest(field=field), self.assertRaises(ValueError):
                encode_status(**invalid)

    def test_all_fixed_errors_and_commands_round_trip(self):
        for error in ERROR_CODES:
            for command in COMMAND_CODES:
                with self.subTest(error=error, command=command):
                    encoded = encode_status("TWAVE", "TASK4", "RUNNING", error, command)
                    decoded = decode_status(encoded)
                    self.assertEqual(decoded["error"], error)
                    self.assertEqual(decoded["command"], command)


if __name__ == "__main__":
    unittest.main()
