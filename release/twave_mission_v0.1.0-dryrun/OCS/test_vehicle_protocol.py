import unittest

from vehicle_protocol import command_payload, decode, encode, make_message, topic


class VehicleProtocolTests(unittest.TestCase):
    def test_round_trip(self):
        message = make_message("T-Wave", "heartbeat", {"state": "IDLE"})
        self.assertEqual(decode(encode(message)), message)
        self.assertIn("run_id", message)
        self.assertIn("source", message)
        self.assertIn("frame_id", message)

    def test_topic_and_command(self):
        self.assertEqual(topic("T-Sky", "command"), "tongji/robotx/v1/T-Sky/command")
        self.assertEqual(command_payload("start_task", task_id="TASK1")["task_id"], "TASK1")
        payload = command_payload(
            "task4_assistance", priority="CRITICAL", preempt=True,
        )
        self.assertEqual(payload["priority"], "CRITICAL")
        self.assertTrue(payload["preempt"])
        self.assertEqual(command_payload("run_start", command_seq=4)["command_seq"], 4)

    def test_invalid_message(self):
        with self.assertRaises(ValueError):
            decode(b'{"kind":"status"}')

    def test_run_and_frame_validation(self):
        message = make_message("T-Wave", "heartbeat", {}, run_id=7, frame_id="usv_ned")
        self.assertEqual(decode(encode(message))["run_id"], 7)
        message["run_id"] = 0
        with self.assertRaises(ValueError):
            encode(message)


if __name__ == "__main__":
    unittest.main()
