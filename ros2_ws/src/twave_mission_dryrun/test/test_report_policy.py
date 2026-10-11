import sys
import unittest
from pathlib import Path

PACKAGE_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PACKAGE_ROOT))

from twave_mission_dryrun.report_policy import decide_report, should_report_error


class ReportPolicyTests(unittest.TestCase):
    def test_timeout_is_status_error_not_fault(self):
        decision = decide_report(error="TIMEOUT")
        self.assertTrue(should_report_error("TIMEOUT"))
        self.assertTrue(decision.include_in_status)
        self.assertFalse(decision.emit_fault)
        self.assertFalse(decision.emit_task_report)

    def test_safe_stop_generates_fault(self):
        decision = decide_report(state="SAFE_STOP")
        self.assertTrue(decision.emit_fault)

    def test_request_abort_generates_fault(self):
        decision = decide_report(command="REQUEST_ABORT")
        self.assertTrue(decision.emit_fault)

    def test_task_complete_generates_task_report(self):
        decision = decide_report(task_result="TASK_COMPLETE")
        self.assertTrue(decision.emit_task_report)
        self.assertFalse(decision.emit_fault)


if __name__ == "__main__":
    unittest.main()
