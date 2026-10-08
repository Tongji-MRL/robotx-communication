import unittest

from fsm_protocol import ack_for, decode, encode, make_message, topic, validate_topic


class StateMachineProtocolTests(unittest.TestCase):
    def make_command(self):
        return make_message(
            "T-Wave",
            "T-Sky",
            "command",
            task="TASK3",
            message_type="TASK3_DELIVERY_REQUEST",
            payload={"resource_color": "RED", "delivery_circle_color": "BLUE"},
            sequence=1,
            run_id=42,
            message_id="command-1",
            sent_at_unix_ms=1,
        )

    def test_round_trip_and_topic(self):
        message = self.make_command()
        decoded = decode(encode(message))
        self.assertEqual(decoded, message)
        expected = "tongji/robotx/fsm/v1/T-Wave/T-Sky/command"
        self.assertEqual(topic("T-Wave", "T-Sky", "command"), expected)
        validate_topic(message, expected)

    def test_ack_reverses_direction_and_correlates(self):
        command = self.make_command()
        ack = ack_for(command, sequence=2, accepted=True, detail="queued")
        self.assertEqual(ack["source_vehicle_id"], "T-Sky")
        self.assertEqual(ack["target_vehicle_id"], "T-Wave")
        self.assertEqual(ack["correlation_id"], "command-1")
        self.assertTrue(ack["payload"]["accepted"])

    def test_same_source_and_target_is_rejected(self):
        with self.assertRaises(ValueError):
            make_message(
                "T-Wave",
                "T-Wave",
                "status",
                task="TASK1",
                message_type="VEHICLE_STATUS",
                payload={},
                sequence=1,
                run_id=42,
            )

    def test_invalid_sequence_and_task_are_rejected(self):
        with self.assertRaises(ValueError):
            make_message(
                "T-Sky",
                "T-Wave",
                "event",
                task="TASK2",
                message_type="TASK_COMPLETE",
                payload={},
                sequence=0,
                run_id=42,
            )

    def test_topic_mismatch_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_topic(
                self.make_command(),
                "tongji/robotx/fsm/v1/T-Sky/T-Wave/command",
            )


if __name__ == "__main__":
    unittest.main()
