"""USV-only boundary regressions; RBC protocol code remains out of scope here."""
from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

import ocs_gateway
from ocs_client import config_values, declaration_values, load_config
from operation_mode import VehicleMode, select_declaration
from vehicle_link import heartbeat_envelope
from vehicle_link import HEARTBEAT_TOPICS, UAV_STATUS_TOPIC


class UsvOnlyGatewayTests(unittest.TestCase):
    def test_gateway_defaults_are_explicitly_usv_only(self):
        self.assertEqual(ocs_gateway.DEFAULT_GATEWAY_CONFIG.name, "config.usv-only.json")
        self.assertEqual(ocs_gateway.VehicleMode.USV_ONLY.value, "usv_only")

    def test_profile_declares_only_twave_and_has_no_uav_configuration(self):
        config = load_config(Path(__file__).with_name("config.usv-only.json"))
        self.assertEqual(config["team_id"], "TONG")
        self.assertEqual(config["mission_coordinator"], "T-Wave")
        self.assertEqual(set(config["vehicles"]), {"usv"})
        tiers, fence, altitude, callsign = declaration_values(config)
        selection = select_declaration(
            VehicleMode.USV_ONLY,
            uav_vehicle_id=None,
            usv_vehicle_id=config["vehicles"]["usv"]["vehicle_id"],
            uav_geofence=fence,
            uav_geofence_max_altitude_hae_m=altitude,
            uav_pilot_callsign=callsign,
            uav_geofence_mode="manual",
        )
        self.assertEqual(selection.vehicle_ids, ["T-Wave"])
        self.assertEqual(selection.uav_geofence, [])
        self.assertIsNone(selection.uav_geofence_max_altitude_hae_m)
        # The deliberate RBC placeholder must still require an operator to set it.
        with self.assertRaisesRegex(ValueError, "robocommand.host"):
            config_values(config)

    def test_usv_only_gateway_disables_uav_ros_and_mqtt_inputs(self):
        captured = {}

        class FakeOcs:
            def __init__(self, *_args, **kwargs):
                captured["mission_coordinator"] = kwargs["mission_coordinator"]

            def accept_fsm_task_report(self, _raw):
                pass

            def accept_fsm_fault(self, _raw):
                pass

            def accept_fsm_status(self, _raw):
                pass

            def accept_uav_status(self, _raw):
                pass

            def accept_vehicle_envelope(self, _value):
                pass

        class FakeRos:
            def __init__(self, *_args, **kwargs):
                captured["ros"] = kwargs

        class FakeLink:
            def __init__(self, *_args, **kwargs):
                captured["link"] = kwargs

        with patch.object(ocs_gateway, "OcsClient", FakeOcs), \
             patch.object(ocs_gateway, "Ros2MissionLink", FakeRos), \
             patch.object(ocs_gateway, "VehicleLink", FakeLink):
            ocs_gateway.OcsGateway(
                official_broker="127.0.0.1", official_port=1883,
                internal_broker="127.0.0.1", internal_port=1883,
                vehicle_mode="usv_only", uav_source_vehicle_id="UAV1",
            )
        self.assertEqual(captured["mission_coordinator"], "T-Wave")
        self.assertIsNone(captured["ros"]["on_uav_geofence_readback"])
        self.assertFalse(captured["ros"]["enable_uav_geofence"])
        self.assertTrue(captured["ros"]["usv_only_run_start"])
        self.assertIsNone(captured["link"]["on_uav_status"])
        self.assertEqual(captured["link"]["heartbeat_topics"],
                         {"/tongji_mrl/twave/heartbeat": "T-Wave"})

    def test_usv_only_forwards_runstart_without_course_ready_ack(self):
        action = {"kind": "internal_command", "vehicle_id": "T-Wave", "command": "RUN_START",
                  "run_id": 42, "command_seq": 7, "course_fingerprint": "current"}
        published = []
        gateway = ocs_gateway.OcsGateway.__new__(ocs_gateway.OcsGateway)
        gateway.ocs = type("Ocs", (), {
            "mission_coordinator": "T-Wave", "drain_internal_actions": lambda _self: [action],
        })()
        gateway.ros2 = type("Ros", (), {
            "available": True, "publish_action": lambda _self, got: (published.append(got) is None, None),
        })()
        gateway.vehicle_mode = VehicleMode.USV_ONLY
        gateway._start_lock = __import__("threading").RLock()
        gateway._clock = lambda: 1.0
        gateway.startup_state = "WAIT_COURSE"
        gateway.startup_reason = "test"
        gateway.pending_course = None
        gateway.course_published_fingerprint = None
        gateway.pending_control_actions = []
        gateway._pending_run_starts = []
        gateway._published_run_starts = []
        gateway.flush_commands()
        self.assertEqual(published, [action])
        self.assertEqual(gateway.pending_control_actions[-1]["state"], "RUNSTART_FORWARDED")

    def test_usv_only_ros2_runstart_payload_is_exact_begin_command(self):
        class Publisher:
            def __init__(self):
                self.messages = []
            def get_subscription_count(self):
                return 1
            def publish(self, message):
                self.messages.append(message)

        publisher = Publisher()
        link = ocs_gateway.Ros2MissionLink.__new__(ocs_gateway.Ros2MissionLink)
        link.available = True
        link.error = None
        link._node = type("Node", (), {"run_start_pub": publisher})()
        link._offline_test_mode = False
        link._usv_only_run_start = True
        link._string = lambda value: value
        sent, reason = link.publish_action({"command": "RUN_START", "run_id": 42, "command_seq": 7})
        self.assertTrue(sent, reason)
        self.assertEqual(publisher.messages, ['{"command":"begin"}'])

    def test_usv_only_mapping_rejects_uav_topic_without_affecting_twave(self):
        topics = {"/tongji_mrl/twave/heartbeat": "T-Wave"}
        payload = {
            "timestamp_unix_ms": 1, "source_mode": "real", "vehicle_type": "usv",
        }
        accepted = heartbeat_envelope("/tongji_mrl/twave/heartbeat", json.dumps(payload),
                                      heartbeat_topics=topics)
        self.assertEqual(accepted["vehicle_id"], "T-Wave")
        with self.assertRaisesRegex(ValueError, "unexpected production heartbeat topic"):
            heartbeat_envelope("/tongji_mrl/tsky/heartbeat", json.dumps(payload),
                               heartbeat_topics=topics)

    def test_uav_interfaces_remain_present_for_explicit_dual_vehicle_mode(self):
        root = Path(__file__).parent
        for filename in ("uav_status.py", "uav_status_mqtt_bridge.py", "uav_geofence.py",
                         "uav_ground_validation.py", "config.uav-status.example.json"):
            self.assertTrue((root / filename).is_file(), filename)
        self.assertEqual(UAV_STATUS_TOPIC, "/tongji_mrl/tsky/uav_status")
        self.assertEqual(HEARTBEAT_TOPICS["/tongji_mrl/tsky/heartbeat"], "T-Sky")
        self.assertEqual(ocs_gateway.MISSION_TOPICS["uav_geofence_apply"],
                         "/tongji_mrl/tsky/uav_geofense_sub")

    def test_dual_vehicle_startup_rejects_incomplete_uav_mapping_before_connecting(self):
        config = {
            "team_id": "TONG", "robocommand": {"host": "127.0.0.1", "port": 1883},
            "vehicles": {"usv": {"vehicle_id": "T-Wave"},
                         "uav": {"vehicle_id": "T-Sky"}},
        }
        with patch.object(ocs_gateway, "load_config", return_value=config), \
             patch.object(ocs_gateway, "config_values", return_value=("TONG", "127.0.0.1", 1883, [])), \
             patch.object(sys, "argv", ["ocs_gateway.py", "--vehicle-mode", "dual_vehicle"]):
            with self.assertRaises(SystemExit) as exited:
                ocs_gateway.main()
        self.assertEqual(exited.exception.code, 2)


if __name__ == "__main__":
    unittest.main()
