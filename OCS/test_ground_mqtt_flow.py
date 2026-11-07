"""Official-MQTT loopback test with explicitly mocked direct ROS input.

The fixture implements only the MQTT 3.1.1 packets used by this test. It is not
a production broker and binds an OS-assigned port on 127.0.0.1 exclusively.
The ROS input is patched at the application boundary; this does not test DDS.
"""
import contextlib
import io
import json
from pathlib import Path
import socket
import struct
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from test_uav_ground_validation import ground_config, course_message, uav_status
from test_ground_scenarios import course_with_northern_transit
import uav_ground_validation as ground
from robotx import rx_commands_pb2, rx_reports_pb2, rx_requests_pb2
import common_pb2


def packet(header, payload):
    size = len(payload)
    encoded_size = bytearray()
    while True:
        digit = size % 128
        size //= 128
        encoded_size.append(digit | (128 if size else 0))
        if not size:
            return bytes([header]) + bytes(encoded_size) + payload


def mqtt_string(value):
    raw = value.encode()
    return struct.pack("!H", len(raw)) + raw


class LoopbackBroker:
    def __init__(self):
        self.server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.server.bind(("127.0.0.1", 0))
        self.port = self.server.getsockname()[1]
        self.server.listen()
        self.server.settimeout(.1)
        self.stop = threading.Event()
        self.lock = threading.RLock()
        self.peers = {}
        self.retained = {}
        self.publications = []
        self.subscriptions = []
        self.threads = []
        self.accept_thread = threading.Thread(target=self._accept, daemon=True)
        self.accept_thread.start()

    def _accept(self):
        while not self.stop.is_set():
            try:
                conn, _ = self.server.accept()
            except socket.timeout:
                continue
            except OSError:
                return
            with self.lock:
                self.peers[conn] = {"topics": set(), "send_lock": threading.Lock()}
            thread = threading.Thread(target=self._client, args=(conn,), daemon=True)
            self.threads.append(thread)
            thread.start()

    @staticmethod
    def _read(conn, count):
        result = b""
        while len(result) < count:
            data = conn.recv(count - len(result))
            if not data:
                raise EOFError()
            result += data
        return result

    def _send(self, conn, data):
        with self.lock:
            peer = self.peers.get(conn)
        if peer is None:
            return
        with peer["send_lock"]:
            conn.sendall(data)

    def _client(self, conn):
        try:
            while not self.stop.is_set():
                header = self._read(conn, 1)[0]
                remaining, multiplier = 0, 1
                for _ in range(4):
                    digit = self._read(conn, 1)[0]
                    remaining += (digit & 127) * multiplier
                    if not digit & 128:
                        break
                    multiplier *= 128
                data = self._read(conn, remaining)
                kind = header >> 4
                if kind == 1:  # CONNECT
                    self._send(conn, b"\x20\x02\x00\x00")
                elif kind == 8:  # SUBSCRIBE
                    message_id, cursor, topics = data[:2], 2, []
                    while cursor < len(data):
                        size = struct.unpack("!H", data[cursor:cursor + 2])[0]
                        cursor += 2
                        name = data[cursor:cursor + size].decode()
                        cursor += size + 1  # Skip requested QoS.
                        topics.append(name)
                    with self.lock:
                        self.peers[conn]["topics"].update(topics)
                        self.subscriptions.extend(topics)
                        retained = [(name, self.retained[name]) for name in topics if name in self.retained]
                    self._send(conn, packet(0x90, message_id + bytes([1] * len(topics))))
                    for name, body in retained:
                        self._send(conn, packet(0x31, mqtt_string(name) + body))
                elif kind == 3:  # PUBLISH
                    size = struct.unpack("!H", data[:2])[0]
                    topic = data[2:2 + size].decode()
                    cursor = 2 + size
                    qos = (header >> 1) & 3
                    message_id = data[cursor:cursor + 2] if qos else None
                    if qos:
                        cursor += 2
                    body = data[cursor:]
                    with self.lock:
                        self.publications.append((topic, body, qos))
                    self.publish(topic, body, retain=bool(header & 1))
                    if qos == 1:
                        self._send(conn, packet(0x40, message_id))
                elif kind == 12:  # PINGREQ
                    self._send(conn, b"\xd0\x00")
                elif kind == 14:  # DISCONNECT
                    return
        except (EOFError, OSError, KeyError):
            pass
        finally:
            with self.lock:
                self.peers.pop(conn, None)
            conn.close()

    def publish(self, topic, body, *, retain=False):
        with self.lock:
            if retain:
                self.retained[topic] = body
            recipients = [conn for conn, peer in self.peers.items() if topic in peer["topics"]]
        for conn in recipients:
            try:
                # A normal forwarded publication is not a retained replay.
                self._send(conn, packet(0x30, mqtt_string(topic) + body))
            except OSError:
                pass

    def snapshot(self):
        with self.lock:
            return list(self.publications)

    def close(self):
        self.stop.set()
        self.server.close()
        with self.lock:
            clients = list(self.peers)
        for conn in clients:
            try:
                conn.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            conn.close()
        self.accept_thread.join(1)
        for thread in self.threads:
            thread.join(1)


class MockRosInput:
    """A test-only direct input stub, never a production simulation option."""
    instances = []

    def __init__(self, session):
        self.session = session
        self.next_sample = 0.0
        self.closed = False
        self.__class__.instances.append(self)

    def connect(self):
        self.session.telemetry_available = True

    def pump(self):
        now = self.session.clock()
        if now >= self.next_sample:
            self.session.on_status(json.dumps(uav_status(
                state="AUTO", timestamp_unix_ms=int(time.time() * 1000))))
            self.next_sample = now + .2

    def close(self):
        self.closed = True
        self.session.on_telemetry_unavailable()


class GroundMqttFlowTests(unittest.TestCase):
    def _run_negative_scenario(self, scenario, *, inject_unexpected_start=False):
        official = LoopbackBroker()
        stop = threading.Event()
        injector = None
        output_buffer = io.StringIO()
        team = "GVSYS2" if scenario == "outside-course" else "GVSYS3"
        course = course_with_northern_transit()
        try:
            official.publish("robocommand/robotx/course", course.SerializeToString(), retain=True)
            config = ground_config()
            config["robocommand"]["port"] = official.port

            def inject_run_start():
                while not stop.wait(.025):
                    captured = official.snapshot()
                    requests = [rx_requests_pb2.RxRequest.FromString(body)
                                for topic, body, _ in captured if topic.endswith("/request")]
                    reports = [body for topic, body, _ in captured if topic.endswith("/report")]
                    if requests and reports:
                        command = rx_commands_pb2.RxCommand(
                            team_id=team, seq=1, run_start=rx_commands_pb2.RunStart(
                                declaration_seq=requests[0].seq, run_id=42))
                        official.publish(f"robocommand/robotx/{team}/command", command.SerializeToString())
                        return

            if inject_unexpected_start:
                injector = threading.Thread(target=inject_run_start, daemon=True)
                injector.start()
            with tempfile.TemporaryDirectory(prefix="robotx-ground-scenario-") as temporary:
                config_path = Path(temporary) / "config.json"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                MockRosInput.instances.clear()
                with patch.object(ground, "Ros2StatusInput", MockRosInput), \
                        contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
                    scenario_options = (["--outside-offset-m", "25"] if scenario == "outside-course"
                                        else ["--test-max-altitude-hae", "63"])
                    result = ground.main([
                        "--config", str(config_path), "--duration", "2.2",
                        "--team-id", team, "--scenario", scenario, *scenario_options])
            output = output_buffer.getvalue()
            captured = official.snapshot()
            self.assertTrue(captured, output)
            self.assertEqual(captured[0][0], f"robocommand/robotx/{team}/request", output)
            requests = [rx_requests_pb2.RxRequest.FromString(body)
                        for topic, body, _ in captured if topic.endswith("/request")]
            reports = [rx_reports_pb2.RxReport.FromString(body)
                       for topic, body, _ in captured if topic.endswith("/report")]
            self.assertEqual(len(requests), 1, output)
            self.assertEqual(requests[0].team_id, team)
            declaration = requests[0].run_declaration
            self.assertEqual(list(declaration.vehicle_ids), ["UAV1"])
            self.assertEqual(declaration.uav_pilot_callsign, "TEST-PILOT")
            for task in range(1, 5):
                self.assertEqual(getattr(declaration, f"task{task}_tier"), common_pb2.TIER_NONE)
            self.assertEqual(declaration.uav_geofence[0], declaration.uav_geofence[-1])
            if scenario == "outside-course":
                northern_limit = max(point.latitude for point in (*course.corners, *course.uav_transit_area))
                self.assertTrue(all(point.latitude > northern_limit for point in declaration.uav_geofence))
                self.assertEqual(declaration.uav_geofence_max_altitude_hae_m, 40.0)
            else:
                self.assertEqual(declaration.uav_geofence_max_altitude_hae_m, 63.0)
                self.assertTrue(all(1.2800 < point.latitude < 1.2820 for point in declaration.uav_geofence))
            self.assertTrue(reports, output)
            self.assertEqual([report.seq for report in reports], list(range(1, len(reports) + 1)))
            for report in reports:
                self.assertEqual((report.team_id, report.vehicle_id), (team, "UAV1"))
                self.assertEqual(report.heartbeat.state, common_pb2.STATE_AUTO)
                self.assertEqual(report.heartbeat.position.latitude, 1.2805)
                self.assertEqual(report.heartbeat.position.longitude, 103.8505)
                self.assertEqual(report.heartbeat.altitude_hae_m, 12.5)
                self.assertAlmostEqual(report.heartbeat.spd_mps, .15)
                self.assertEqual(report.heartbeat.heading_deg, 178.0)
            self.assertTrue(all(qos == 1 for _, _, qos in captured))
            self.assertEqual(set(official.subscriptions), {
                "robocommand/robotx/course", f"robocommand/robotx/{team}/command"})
            self.assertEqual({topic for topic, _, _ in captured}, {
                f"robocommand/robotx/{team}/request", f"robocommand/robotx/{team}/UAV1/report"})
            self.assertEqual(len(MockRosInput.instances), 1)
            self.assertTrue(MockRosInput.instances[0].closed)
            events = [json.loads(line) for line in output.splitlines() if line.startswith('{"event":')]
            self.assertTrue(all(event["scenario"] == scenario and event["team_id"] == team
                                for event in events), output)
            self.assertFalse(any(event["event"] == "RUN_START_RECORDED" for event in events), output)
            evidence = next(event for event in events if event["event"] == "DECLARATION_PUBLISHED")
            self.assertEqual(evidence["outcome"], "acceptance_unknown")
            self.assertEqual(evidence["maximum_height_hae_m"], declaration.uav_geofence_max_altitude_hae_m)
            self.assertEqual(evidence["uav_geofence"], [
                {"latitude": point.latitude, "longitude": point.longitude}
                for point in declaration.uav_geofence])
            if inject_unexpected_start:
                self.assertEqual(result, 2, output)
                self.assertIn("RunStart", output)
                self.assertTrue(any(event["event"] == "SCENARIO_FAILED" and event["outcome"] == "failed"
                                    for event in events), output)
            else:
                self.assertEqual(result, 0, output)
                self.assertGreaterEqual(len(reports), 3, output)
                ending = next(event for event in events if event["event"] == "GROUND_SESSION_END")
                self.assertEqual(ending["outcome"], "acceptance_unknown",
                                 "No RunStart does not prove backend rejection")
            return events, output
        finally:
            stop.set()
            if injector is not None:
                injector.join(1)
            official.close()

    def test_outside_scenario_uses_same_ros_input_and_real_mqtt_publication_path(self):
        self._run_negative_scenario("outside-course")

    def test_over_height_scenario_uses_same_ros_input_and_real_mqtt_publication_path(self):
        self._run_negative_scenario("over-height")

    def test_negative_matching_run_start_fails_main_and_closes_ros_input(self):
        self._run_negative_scenario("over-height", inject_unexpected_start=True)

    def test_main_with_mock_ros_input_declares_then_streams_and_records_run_start(self):
        official = LoopbackBroker()
        stop = threading.Event()
        injected_start = threading.Event()
        injector = None
        output_buffer = io.StringIO()
        try:
            official.publish("robocommand/robotx/course", course_message().SerializeToString(), retain=True)
            config = ground_config()
            config["robocommand"]["port"] = official.port

            def inject_run_start():
                while not stop.wait(.025):
                    captured = official.snapshot()
                    declarations = [rx_requests_pb2.RxRequest.FromString(body)
                                    for topic, body, _ in captured if topic.endswith("/request")]
                    reports = [rx_reports_pb2.RxReport.FromString(body)
                               for topic, body, _ in captured if topic.endswith("/report")]
                    if declarations and reports:
                        command = rx_commands_pb2.RxCommand(
                            team_id="TONG", seq=1, run_start=rx_commands_pb2.RunStart(
                                declaration_seq=declarations[0].seq, run_id=42))
                        official.publish("robocommand/robotx/TONG/command", command.SerializeToString())
                        injected_start.set()
                        return

            injector = threading.Thread(target=inject_run_start, daemon=True)
            injector.start()
            with tempfile.TemporaryDirectory(prefix="robotx-ground-test-") as temporary:
                config_path = Path(temporary) / "config.json"
                config_path.write_text(json.dumps(config), encoding="utf-8")
                MockRosInput.instances.clear()
                with patch.object(ground, "Ros2StatusInput", MockRosInput), \
                        contextlib.redirect_stdout(output_buffer), contextlib.redirect_stderr(output_buffer):
                    result = ground.main(["--config", str(config_path), "--duration", "3",
                                          "--vehicle-id", "UAV-CLI"])
            output = output_buffer.getvalue()
            self.assertEqual(result, 0, output)
            captured = official.snapshot()
            self.assertTrue(captured, output)
            self.assertEqual(captured[0][0], "robocommand/robotx/TONG/request", output)
            declarations = [rx_requests_pb2.RxRequest.FromString(body)
                            for topic, body, _ in captured if topic.endswith("/request")]
            reports = [rx_reports_pb2.RxReport.FromString(body)
                       for topic, body, _ in captured if topic.endswith("/report")]
            self.assertEqual(len(declarations), 1, output)
            self.assertEqual(list(declarations[0].run_declaration.vehicle_ids), ["UAV-CLI"])
            self.assertGreaterEqual(len(reports), 4, output)
            self.assertEqual([report.seq for report in reports], list(range(1, len(reports) + 1)))
            self.assertTrue(all(report.heartbeat.state == common_pb2.STATE_AUTO for report in reports))
            self.assertTrue(all(report.vehicle_id == "UAV-CLI" for report in reports))
            self.assertTrue(all(qos == 1 for _, _, qos in captured))
            self.assertTrue(injected_start.is_set(), output)
            events = [json.loads(line) for line in output.splitlines() if line.startswith('{"event":')]
            run_events = [event for event in events if event["event"] == "RUN_START_RECORDED"]
            self.assertEqual(len(run_events), 1, output)
            self.assertEqual(run_events[0]["run_id"], 42)
            self.assertEqual(run_events[0]["declaration_seq"], declarations[0].seq)
            self.assertEqual(run_events[0]["vehicle_commands_sent"], 0)
            self.assertTrue(all(event["vehicle_id"] == "UAV-CLI" for event in events))
            start_event = next(event for event in events if event["event"] == "GROUND_SESSION_START")
            self.assertEqual(start_event["source_vehicle_id"], "UAV1")
            self.assertEqual(set(official.subscriptions), {
                "robocommand/robotx/course", "robocommand/robotx/TONG/command"})
            self.assertTrue(all(topic.endswith(("/request", "/UAV-CLI/report")) for topic, _, _ in captured))
            self.assertEqual(len(MockRosInput.instances), 1)
            self.assertTrue(MockRosInput.instances[0].closed)
        finally:
            stop.set()
            if injector is not None:
                injector.join(1)
            official.close()


if __name__ == "__main__":
    unittest.main()
