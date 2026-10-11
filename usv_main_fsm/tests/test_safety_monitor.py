import unittest
from pathlib import Path

from usv_main_fsm.checkpoint_store import CheckpointStore
from usv_main_fsm.coordinator import MissionCoordinator
from usv_main_fsm.models import Ack, MainState, TaskId, Target
from usv_main_fsm.safety_models import SafetyEvent, SafetyFaultType, SafetyLevel
from usv_main_fsm.safety_monitor import SafetyMonitor


class SafetyMonitorTests(unittest.TestCase):
    def setUp(self):
        self.path = Path.cwd() / "usv_main_fsm" / ".safety-test.json"
        self.path.unlink(missing_ok=True)
        self.coordinator = MissionCoordinator(CheckpointStore(self.path), task_targets={t: (Target.USV,) for t in TaskId})
        self.coordinator.start_run(77)
        self.monitor = SafetyMonitor()

    def tearDown(self):
        self.path.unlink(missing_ok=True)
        self.coordinator.safety_latch_store.path.unlink(missing_ok=True)

    def event(self, ident, fault, active=True, run_id=77, trustworthy=True, clears=None):
        return SafetyEvent(ident, run_id, fault, active, "test", 1.0, trustworthy, fault.value, clears)

    def test_communication_timeout_requests_hold_and_clear_never_auto_resumes(self):
        decision = self.monitor.ingest(self.event("ocs-lost", SafetyFaultType.OCS_LINK_LOST), current_run_id=77)
        hold_actions = self.coordinator.request_safe_hold(77, reason=decision.reason)
        for action in hold_actions:
            self.coordinator.receive_ack(Ack(action.command_id, 77, action.target, True, True, "safe-phase"))
        self.assertEqual(self.coordinator.state, MainState.SAFE_HOLD)
        self.assertIsNotNone(self.coordinator.checkpoint)
        cleared = self.monitor.ingest(self.event("ocs-back", SafetyFaultType.OCS_LINK_LOST, False, clears="ocs-lost"), current_run_id=77)
        self.assertEqual(cleared.level, SafetyLevel.NORMAL)
        self.assertEqual(self.coordinator.state, MainState.SAFE_HOLD)
        self.assertEqual(self.coordinator.release_safe_hold(77, health_verified=True, recovery_permitted=False, vehicles_safe=True), [])

    def test_hold_escalates_and_critical_directly_latches_stop(self):
        hold = self.monitor.ingest(self.event("nav", SafetyFaultType.NAVIGATION_LOST), current_run_id=77)
        self.coordinator.request_safe_hold(77, reason=hold.reason)
        critical = self.monitor.ingest(self.event("motion", SafetyFaultType.UNCONTROLLED_MOTION), current_run_id=77)
        self.coordinator.safe_stop(77, reason=critical.reason, source="SafetyMonitor")
        self.assertEqual(self.coordinator.state, MainState.SAFE_STOP)

    def test_stop_persists_reset_requires_all_conditions_and_returns_idle_only(self):
        self.coordinator.safe_stop(77, reason="manual", source="SafetyMonitor")
        restarted = MissionCoordinator(CheckpointStore(self.path), task_targets={t: (Target.USV,) for t in TaskId})
        self.assertEqual(restarted.state, MainState.SAFE_STOP)
        self.assertFalse(restarted.reset_safe_stop(authorization_id="test", authorization_run_id=76, severe_faults_clear=True, executors_safe=True, failsafe_cleared=True, reinitialize_ready=True))
        self.assertEqual(restarted.state, MainState.SAFE_STOP)
        self.assertFalse(restarted.reset_safe_stop(authorization_id="test", authorization_run_id=77, severe_faults_clear=False, executors_safe=True, failsafe_cleared=True, reinitialize_ready=True))
        self.assertTrue(restarted.reset_safe_stop(authorization_id="test", authorization_run_id=77, severe_faults_clear=True, executors_safe=True, failsafe_cleared=True, reinitialize_ready=True))
        self.assertEqual(restarted.state, MainState.IDLE)
        self.assertIsNone(restarted.run_id)

    def test_highest_level_wins_old_duplicate_and_untrusted_data_never_lower_safety(self):
        self.assertEqual(self.monitor.ingest(self.event("sensor", SafetyFaultType.SENSOR_UNHEALTHY), current_run_id=77).level, SafetyLevel.HOLD)
        self.assertEqual(self.monitor.ingest(self.event("estop", SafetyFaultType.MANUAL_ESTOP), current_run_id=77).level, SafetyLevel.CRITICAL)
        self.assertIsNone(self.monitor.ingest(self.event("old", SafetyFaultType.MANUAL_ESTOP, run_id=76), current_run_id=77))
        self.assertIsNone(self.monitor.ingest(self.event("estop", SafetyFaultType.MANUAL_ESTOP), current_run_id=77))
        self.assertEqual(self.monitor.mark_monitor_fault().level, SafetyLevel.CRITICAL)

    def test_monitor_unknown_is_not_normal(self):
        self.assertEqual(SafetyMonitor().mark_monitor_fault().level, SafetyLevel.HOLD)
