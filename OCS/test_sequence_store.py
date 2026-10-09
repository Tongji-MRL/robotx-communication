import json
import tempfile
import unittest
from pathlib import Path

from sequence_store import SequenceStore


class SequenceStoreTests(unittest.TestCase):
    def test_counters_survive_restart(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ocs_state.json"
            first = SequenceStore(path)
            self.assertEqual(first.next_team_seq(), 1)
            self.assertEqual(first.next_report_seq("T-Wave"), 1)
            first.observe_command_seq(7)

            second = SequenceStore(path)
            self.assertEqual(second.next_team_seq(), 2)
            self.assertEqual(second.next_report_seq("T-Wave"), 2)
            self.assertEqual(second.last_command_seq, 7)

    def test_invalid_state_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ocs_state.json"
            path.write_text(json.dumps({"version": 999}), encoding="utf-8")
            with self.assertRaises(ValueError):
                SequenceStore(path)

    def test_memory_mode_does_not_create_a_file(self) -> None:
        store = SequenceStore()
        self.assertEqual(store.next_team_seq(), 1)
        self.assertEqual(store.next_report_seq("T-Sky"), 1)


if __name__ == "__main__":
    unittest.main()
