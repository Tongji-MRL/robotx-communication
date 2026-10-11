import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from twave_mission_dryrun.vehicle_status_store import VehicleStatusStore


class VehicleStatusStoreTests(unittest.TestCase):
    def setUp(self):
        self.now = 100.0
        self.store = VehicleStatusStore(clock=lambda: self.now)

    def test_single_vehicle_update(self):
        self.store.update("T-Wave", "10100000000000")
        self.assertEqual(self.store.get("T-Wave"), {
            "status_bits": "10100000000000", "timestamp": 100.0,
        })

    def test_two_vehicles_are_preserved(self):
        self.store.update("T-Wave", "10100000000000")
        self.store.update("T-Sky", "00000000000000")
        self.assertEqual(self.store.get_all(), {
            "T-Wave": {"status_bits": "10100000000000", "timestamp": 100.0},
            "T-Sky": {"status_bits": "00000000000000", "timestamp": 100.0},
        })

    def test_new_update_overwrites_vehicle_snapshot(self):
        self.store.update("T-Wave", "10100000000000")
        self.now = 101.0
        self.store.update("T-Wave", "10100100000000")
        self.assertEqual(self.store.get_all(), {
            "T-Wave": {"status_bits": "10100100000000", "timestamp": 101.0},
        })
