"""Local-only Fake RoboCommand RunStart test.

Start this receiver BEFORE restarting Windows OCS Gateway with
--publish-declaration. On receiving its actual RunDeclaration, this script
publishes a valid retained test RxCourse and a matching RunStart. It never
issues internal vehicle commands directly.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
import time
from pathlib import Path

import paho.mqtt.client as mqtt

# Install this script under robotx-communication/fake_rbc/.
ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "RobotX_2026" / "gen" / "python"
if not GENERATED.is_dir():
    raise SystemExit(f"Official protobuf Python directory not found: {GENERATED}")
sys.path.insert(0, str(GENERATED))
from robotx import rx_commands_pb2, rx_course_pb2, rx_reports_pb2, rx_requests_pb2  # noqa: E402

COURSE_TOPIC = "robocommand/robotx/course"


def ensure_published(client: mqtt.Client, topic: str, message, *, retain=False):
    info = client.publish(topic, message.SerializeToString(), qos=1, retain=retain)
    if info.rc != mqtt.MQTT_ERR_SUCCESS:
        raise RuntimeError(f"Publish rejected by MQTT client on {topic}: rc={info.rc}")
    info.wait_for_publish(timeout=5)
    if not info.is_published():
        raise TimeoutError(f"Timed out waiting for MQTT publish: {topic}")


def main():
    parser = argparse.ArgumentParser(description="Fake RBC: capture real declaration_seq and issue matched RunStart")
    parser.add_argument("--config", type=Path, default=ROOT / "OCS" / "config.flight.local.json",
                        help="local OCS config; team and UAV vehicle ID are read from it")
    parser.add_argument("--team-id", help="override team_id from --config")
    parser.add_argument("--vehicle-id", help="override vehicles.uav.vehicle_id from --config")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--wait", type=float, default=120, help="seconds to wait for a new RunDeclaration")
    args = parser.parse_args()

    try:
        config = json.loads(args.config.read_text(encoding="utf-8"))
        team = str(args.team_id or config["team_id"])
        vehicle_id = str(args.vehicle_id or config["vehicles"]["uav"]["vehicle_id"])
    except (OSError, KeyError, TypeError, ValueError) as exc:
        raise SystemExit(f"[ERROR] Cannot load Fake RBC identity from {args.config}: {exc}")
    if not team or not vehicle_id:
        raise SystemExit("[ERROR] team_id and vehicles.uav.vehicle_id must be non-empty")
    if args.host != "127.0.0.1" or args.port != 1883:
        raise SystemExit("[ERROR] Fake RBC is restricted to 127.0.0.1:1883")
    req_topic = f"robocommand/robotx/{team}/request"
    cmd_topic = f"robocommand/robotx/{team}/command"
    report_topic = f"robocommand/robotx/{team}/{vehicle_id}/report"

    found = threading.Event()
    heartbeat_found = threading.Event()
    box: dict[str, object] = {}

    def on_connect(client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            print(f"[ERROR] Official broker refused connection: {reason_code}", flush=True)
            return
        # Publish Course before Declaration: the OCS must bind its Declaration
        # to a valid Course, rather than accepting a test-only ordering shortcut.
        course = rx_course_pb2.RxCourse()
        course.course_id = "LOCAL_FAKE_RBC_COURSE"
        course.pinger_freq_hz = 37
        for latitude, longitude in [(1.2800, 103.8500), (1.2800, 103.8600),
                                    (1.2700, 103.8600), (1.2700, 103.8500),
                                    (1.2800, 103.8500)]:
            corner = course.corners.add()
            corner.latitude, corner.longitude = latitude, longitude
        course.sent_at.GetCurrentTime()
        ensure_published(client, COURSE_TOPIC, course, retain=True)
        client.subscribe([(req_topic, 1), (report_topic, 1)])
        print(f"[COURSE] Published valid retained RxCourse on {COURSE_TOPIC}", flush=True)
        print(f"[READY] Subscribed to {req_topic} and {report_topic}; expected UAV-only vehicle_id={vehicle_id!r}", flush=True)

    def on_message(_client, _userdata, message):
        if message.topic == req_topic and not found.is_set():
            request = rx_requests_pb2.RxRequest()
            try:
                request.ParseFromString(message.payload)
            except Exception as exc:
                print(f"[WARN] Invalid RxRequest protobuf: {exc}", flush=True)
                return
            if request.team_id != team or request.WhichOneof("body") != "run_declaration":
                print("[WARN] Ignoring RxRequest that is not this team's RunDeclaration", flush=True)
                return
            vehicle_ids = list(request.run_declaration.vehicle_ids)
            print(f"[DECLARATION] seq={request.seq} vehicle_ids={vehicle_ids}", flush=True)
            if request.seq <= 0 or vehicle_ids != [vehicle_id]:
                print("[ERROR] Declaration must have a positive seq and exactly the configured UAV-only vehicle; not sending RunStart", flush=True)
                return
            box["declaration_seq"] = request.seq
            found.set()
        elif message.topic == report_topic and found.is_set() and not heartbeat_found.is_set():
            report = rx_reports_pb2.RxReport()
            try:
                report.ParseFromString(message.payload)
                if (report.team_id != team or report.vehicle_id != vehicle_id or report.seq <= 0
                        or report.WhichOneof("body") != "heartbeat"):
                    raise ValueError("not a matching UAV Heartbeat")
            except Exception as exc:
                print(f"[WARN] Ignoring invalid/non-UAV official report: {exc}", flush=True)
                return
            heartbeat_found.set()
            print(f"[HEARTBEAT] Received official UAV Heartbeat vehicle_id={vehicle_id} seq={report.seq}", flush=True)

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.host, args.port, keepalive=60)
    client.loop_start()
    try:
        if not found.wait(args.wait):
            raise SystemExit("[TIMEOUT] No valid new RunDeclaration received. Restart OCS Gateway AFTER [READY].")
        if not heartbeat_found.wait(args.wait):
            raise SystemExit("[TIMEOUT] No valid official UAV Heartbeat received after Declaration; RunStart withheld.")

        command = rx_commands_pb2.RxCommand()
        command.team_id = team
        command.seq = 1  # First simulated RoboCommand command in fresh gateway session.
        command.sent_at.GetCurrentTime()
        command.run_start.declaration_seq = int(box["declaration_seq"])
        command.run_start.run_id = int(time.time())  # Positive test run ID, avoids reuse across tests.
        ensure_published(client, cmd_topic, command)
        print(
            f"[RUN_START] Published command_seq={command.seq} "
            f"declaration_seq={command.run_start.declaration_seq} "
            f"run_id={command.run_start.run_id}",
            flush=True,
        )
        print("[CHECK] Inspect OCS [RunStart]/[TxCommand] logs, then Ubuntu ROS status.", flush=True)
    finally:
        client.loop_stop()
        client.disconnect()


if __name__ == "__main__":
    main()
