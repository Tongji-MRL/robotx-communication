"""Offline compatibility checks for fake_vehicle_heartbeat_sender."""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT.parent / "robotx-monitor-ui" / "OCS"))
from heartbeat_cache import HeartbeatCache  # noqa: E402

SPEC = importlib.util.spec_from_file_location("fake_sender", ROOT / "fake_rbc" / "fake_vehicle_heartbeat_sender.py")
sender = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(sender)


class FakeHeartbeatSenderTests(unittest.TestCase):
    def _accept(self, vehicle_id):
        raw = sender.heartbeat_payload(vehicle_id, run_id=42, now_ms=1_000_000, message_id=f"{vehicle_id}-1")
        envelope = {"kind": "heartbeat", "vehicle_id": vehicle_id, "source": vehicle_id,
                    "payload": json.loads(json.dumps(raw)), **raw}
        HeartbeatCache(now_ms=lambda: 1_000_000).accept(envelope, active_run_id=42)
        return raw

    def test_twave_matches_gateway_topic_and_cache(self):
        raw = self._accept("T-Wave")
        self.assertEqual(sender.HEARTBEAT_TOPICS["T-Wave"], "/tongji_mrl/twave/heartbeat")
        self.assertEqual((raw["source_mode"], raw["vehicle_type"]), ("simulation", "usv"))
        self.assertNotIn("uav_registration", raw)

    def test_tsky_matches_gateway_topic_and_cache(self):
        raw = self._accept("T-Sky")
        self.assertEqual(sender.HEARTBEAT_TOPICS["T-Sky"], "/tongji_mrl/tsky/heartbeat")
        self.assertEqual(raw["flight_phase"], "grounded")
        self.assertEqual(raw["health"], {"fcu_connected": True, "simulator": True})

    def test_ids_are_new_and_timestamps_are_not_hard_coded(self):
        first = sender.heartbeat_payload("T-Wave", run_id=None, now_ms=1_000_000)
        second = sender.heartbeat_payload("T-Wave", run_id=None, now_ms=1_000_001)
        self.assertNotEqual(first["message_id"], second["message_id"])
        self.assertLess(first["sent_at_unix_ms"], second["sent_at_unix_ms"])

    def test_main_defaults_to_dry_run(self):
        old = sys.argv
        try:
            sys.argv = ["fake_vehicle_heartbeat_sender.py"]
            self.assertEqual(sender.main(), 0)
        finally:
            sys.argv = old


if __name__ == "__main__":
    unittest.main()
