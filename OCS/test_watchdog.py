import unittest

from watchdog import OcsWatchdog


class WatchdogTests(unittest.TestCase):
    def test_heartbeat_timeout_is_reported_once_until_recovery(self) -> None:
        watchdog = OcsWatchdog(heartbeat_timeout_s=3, command_ack_timeout_s=5)
        watchdog.start_run(["T-Sky", "T-Wave"], now=10)
        self.assertEqual(watchdog.check(12), [])
        self.assertEqual(watchdog.check(13)[0]["kind"], "heartbeat_timeout")
        self.assertEqual(watchdog.check(20), [])
        watchdog.note_heartbeat("T-Sky", 20)
        watchdog.note_heartbeat("T-Wave", 20)
        self.assertEqual(watchdog.check(22), [])

    def test_ack_timeout_clears_when_acknowledged(self) -> None:
        watchdog = OcsWatchdog(heartbeat_timeout_s=3, command_ack_timeout_s=5)
        watchdog.start_run([], now=0)
        watchdog.note_command_sent(9, 1)
        self.assertEqual(watchdog.check(4), [])
        self.assertEqual(watchdog.check(6)[0]["command_seq"], 9)
        watchdog.note_ack(9)
        self.assertEqual(watchdog.check(100), [])

    def test_watchdog_does_not_choose_or_send_a_command(self) -> None:
        watchdog = OcsWatchdog()
        watchdog.start_run(["T-Wave"], now=0)
        event = watchdog.check(3)[0]
        self.assertEqual(event["kind"], "heartbeat_timeout")
        self.assertNotIn("command", event)


if __name__ == "__main__":
    unittest.main()
