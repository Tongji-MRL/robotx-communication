import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PACKAGE_ROOT), str(PACKAGE_ROOT.parents[2])]

from twave_mission_dryrun.mission_event_router import MissionEventRouter
from twave_mission_dryrun.progress_decoder import decode_progress
from twave_mission_dryrun.report_manager import FAULT_TOPIC, STATUS_TOPIC, TASK_REPORT_TOPIC


class ProgressEventRouterTests(unittest.TestCase):
    def setUp(self):
        self.router = MissionEventRouter()

    def test_normal_progress_is_decoded(self):
        decoded = decode_progress("T-Wave", "10100000000000")
        self.assertEqual(decoded, {
            "vehicle": "T-Wave", "status_bits": "10100000000000",
            "task": "TASK1", "progress": "READY", "error": "NONE", "command": "NONE",
        })

    def test_task_complete_triggers_task_report(self):
        # T-Wave, TASK1, COMPLETE, NONE, REPORT_TASK_COMPLETE
        messages = self.router.route_progress("T-Wave", "10111110000100")
        self.assertEqual([message.topic for message in messages], [STATUS_TOPIC, TASK_REPORT_TOPIC])

    def test_safe_hold_triggers_fault(self):
        # T-Wave, NOT_STARTED, READY, NONE, REQUEST_SAFE_HOLD
        messages = self.router.route_progress("T-Wave", "10000000000110")
        self.assertEqual([message.topic for message in messages], [STATUS_TOPIC, FAULT_TOPIC])

    def test_timeout_does_not_trigger_fault(self):
        # T-Wave, TASK1, READY, TIMEOUT, NONE
        messages = self.router.route_progress("T-Wave", "10100000001000")
        self.assertEqual([message.topic for message in messages], [STATUS_TOPIC])
