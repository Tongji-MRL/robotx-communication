import threading
import types
import unittest
from unittest.mock import patch

import ocs_gateway
from ocs_gateway import OcsGateway
from operation_mode import VehicleMode
from uav_status import normalize_uav_status


def gateway_with(ocs, ros2):
    gateway = OcsGateway.__new__(OcsGateway)
    gateway.ocs = ocs
    gateway.ros2 = ros2
    gateway.vehicle_mode = VehicleMode.UAV_ONLY
    gateway._start_lock = threading.RLock()
    gateway._clock = lambda: 1.0
    gateway.startup_state = "WAIT_COURSE"
    gateway.startup_reason = "test"
    gateway.pending_course = None
    gateway.course_published_fingerprint = None
    gateway.pending_control_actions = []
    gateway._pending_run_starts = []
    gateway._published_run_starts = []
    return gateway


class UavOnlyGatewayStateTests(unittest.TestCase):
    def test_uav_only_connect_does_not_require_internal_vehicle_mqtt(self):
        calls = []
        gateway = OcsGateway.__new__(OcsGateway)
        gateway.vehicle_mode = VehicleMode.UAV_ONLY
        gateway.ocs = types.SimpleNamespace(
            connect=lambda: calls.append("official"),
            queue_course_sync=lambda: calls.append("course"),
        )
        gateway.vehicle_link = types.SimpleNamespace(connect=lambda: self.fail("must not connect internal MQTT"))
        gateway.connect()
        self.assertEqual(calls, ["official", "course"])

    def test_blocked_geofence_keeps_uav_only_gateway_running_without_declaration(self):
        instances = []

        class Gateway:
            def __init__(self, **_kwargs):
                self.ocs = types.SimpleNamespace(course_store=types.SimpleNamespace(get=lambda: object()))
                self.declaration_calls = []
                self.run_calls = []
                instances.append(self)

            def connect(self):
                pass

            def publish_uav_geofence_candidate(self, **_kwargs):
                return False

            def arm_uav_auto_declaration(self, **_kwargs):
                pass

            def publish_declaration(self, *args, **kwargs):
                self.declaration_calls.append((args, kwargs))

            def run(self, duration):
                self.run_calls.append(duration)

            def close(self):
                pass

        selection = types.SimpleNamespace(
            vehicle_ids=["T-Sky"], uav_geofence=[(1.0, 2.0)] * 4,
            uav_geofence_max_altitude_hae_m=40.0, uav_pilot_callsign="PILOT",
            uav_geofence_mode="manual",
        )
        config = {"vehicles": {"uav": {"vehicle_id": "T-Sky"}, "usv": {"vehicle_id": "T-Wave"}}}
        with patch.object(ocs_gateway, "OcsGateway", Gateway), \
             patch.object(ocs_gateway, "load_config", return_value=config), \
             patch.object(ocs_gateway, "config_values", return_value=("TONG", "offline", 1883, ["T-Sky"])), \
             patch.object(ocs_gateway, "declaration_values", return_value=(("none",) * 4, [], 40.0, "PILOT")), \
             patch.object(ocs_gateway, "geofence_options", return_value=("manual", 2.0, 50.0)), \
             patch.object(ocs_gateway, "select_declaration", return_value=selection), \
             patch("sys.argv", ["ocs_gateway.py", "--publish-declaration", "--vehicle-mode", "uav_only", "--duration", "0.25"]):
            self.assertEqual(ocs_gateway.main(), 0)

        self.assertEqual(instances[0].declaration_calls, [])
        self.assertEqual(instances[0].run_calls, [0.25])

    def test_undeclared_uav_status_never_produces_a_heartbeat(self):
        client = ocs_gateway.OcsClient("127.0.0.1", 1883)
        published = []
        client._publish = lambda topic, message: published.append((topic, message))
        now = 1_700_000_000_000
        status = normalize_uav_status({
            "vehicle_id": "UAV1", "vehicle_type": "TYPE_UAV", "state": "STATE_AUTO",
            "flight_phase": "FLIGHT_PHASE_AIRBORNE", "position": {"latitude": 1.2, "longitude": 103.8},
            "altitude_hae_m": 20.0, "spd_mps": 4.0, "heading_deg": 180.0,
            "timestamp_unix_ms": now, "source_mode": "real", "roll_deg": 1.0, "pitch_deg": -2.0,
            "current_task": "TASK_NONE", "health": {"fcu_connected": True},
            "uav_registration": "TEST-UAV-001",
        }, source_vehicle_id="UAV1", vehicle_id="T-Sky", received_unix_ms=now)

        client.accept_uav_status(status)
        self.assertEqual(client.publish_cached_heartbeats(), 0)
        self.assertEqual(published, [])

    def test_fsm_status_does_not_drive_uav_only_state(self):
        received = []
        gateway = gateway_with(types.SimpleNamespace(accept_fsm_status=received.append), types.SimpleNamespace())
        gateway._on_fsm_status("{ignored}")
        self.assertEqual(received, ["{ignored}"])
        self.assertEqual(gateway.startup_state, "WAIT_COURSE")

    def test_course_is_recorded_without_twave_publish_or_ack_wait(self):
        action = {"kind": "course_config", "vehicle_id": "T-Wave", "payload": {"course_id": "C"}}
        ros2 = types.SimpleNamespace(available=True, publish_course=lambda _payload: self.fail("must not publish to T-Wave"))
        ocs = types.SimpleNamespace(mission_coordinator="T-Wave", drain_internal_actions=lambda: [action])
        gateway = gateway_with(ocs, ros2)
        gateway.flush_commands()
        self.assertEqual(gateway.startup_state, "COURSE_RECEIVED")
        self.assertIn("UAV geofence", gateway.startup_reason)

    def test_runstart_is_still_blocked_without_orin_contract(self):
        action = {"kind": "internal_command", "vehicle_id": "T-Wave", "command": "RUN_START",
                  "run_id": 42, "command_seq": 9}
        ros2 = types.SimpleNamespace(available=True, publish_action=lambda _action: self.fail("must not publish RunStart"))
        ocs = types.SimpleNamespace(mission_coordinator="T-Wave", drain_internal_actions=lambda: [action])
        gateway = gateway_with(ocs, ros2)
        gateway.flush_commands()
        self.assertEqual(gateway.startup_state, "RUNSTART_ORIN_INTERFACE_UNAVAILABLE")
        self.assertEqual(gateway.pending_control_actions[-1]["state"], "BLOCKED_UAV_TASK_RECEIVER_UNAVAILABLE")

    def test_declaration_does_not_query_twave_course_ready(self):
        published = []
        ocs = types.SimpleNamespace(
            publish_run_declaration=lambda *args, **kwargs: published.append((args, kwargs)),
            is_current_course_ready=lambda: self.fail("must not query T-Wave FSM readiness"),
        )
        gateway = gateway_with(ocs, types.SimpleNamespace())
        gateway.publish_declaration(["T-Sky"], ("none",) * 4, [(1.0, 2.0)] * 4,
                                    40.0, "PILOT")
        self.assertTrue(published)
        self.assertEqual(gateway.startup_state, "DECLARATION_SENT")

