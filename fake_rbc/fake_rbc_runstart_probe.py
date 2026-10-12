"""Local-only Fake RoboCommand RunStart test.

Start this receiver BEFORE restarting Windows OCS Gateway with
--publish-declaration. On receiving its actual RunDeclaration, this script
publishes a valid retained test RxCourse and a matching RunStart. It never
issues internal vehicle commands directly.
"""
from __future__ import annotations

import argparse
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
from robotx import rx_commands_pb2, rx_course_pb2, rx_requests_pb2  # noqa: E402

TEAM = "TONG"
REQ_TOPIC = f"robocommand/robotx/{TEAM}/request"
CMD_TOPIC = f"robocommand/robotx/{TEAM}/command"
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
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=1883)
    parser.add_argument("--wait", type=float, default=120, help="seconds to wait for a new RunDeclaration")
    args = parser.parse_args()

    found = threading.Event()
    box: dict[str, object] = {}

    def on_connect(client, _userdata, _flags, reason_code, _properties):
        if reason_code != 0:
            print(f"[ERROR] Official broker refused connection: {reason_code}", flush=True)
            return
        client.subscribe(REQ_TOPIC, qos=1)
        print(f"[READY] Subscribed to {REQ_TOPIC}", flush=True)
        print("[ACTION] Now restart the Windows OCS Gateway with --publish-declaration", flush=True)

    def on_message(_client, _userdata, message):
        if message.topic != REQ_TOPIC or found.is_set():
            return
        request = rx_requests_pb2.RxRequest()
        try:
            request.ParseFromString(message.payload)
        except Exception as exc:
            print(f"[WARN] Invalid RxRequest protobuf: {exc}", flush=True)
            return
        if request.team_id != TEAM or request.WhichOneof("body") != "run_declaration":
            print("[WARN] Ignoring RxRequest that is not TONG RunDeclaration", flush=True)
            return
        vehicle_ids = list(request.run_declaration.vehicle_ids)
        print(f"[DECLARATION] seq={request.seq} vehicle_ids={vehicle_ids}", flush=True)
        if request.seq <= 0 or not {"T-Wave", "T-Sky"}.issubset(set(vehicle_ids)):
            print("[ERROR] Declaration is missing a positive seq or expected vehicles; not sending RunStart", flush=True)
            return
        box["declaration_seq"] = request.seq
        found.set()

    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    client.on_connect = on_connect
    client.on_message = on_message
    client.connect(args.host, args.port, keepalive=60)
    client.loop_start()
    try:
        if not found.wait(args.wait):
            raise SystemExit("[TIMEOUT] No valid new RunDeclaration received. Restart OCS Gateway AFTER [READY].")

        course = rx_course_pb2.RxCourse()
        course.course_id = "LOCAL_FAKE_RBC_COURSE"
        course.pinger_freq_hz = 37
        # Closed test polygon near Singapore. Never use as a real mission course.
        vertices = [
            (1.2800, 103.8500),
            (1.2800, 103.8600),
            (1.2700, 103.8600),
            (1.2700, 103.8500),
            (1.2800, 103.8500),
        ]
        for latitude, longitude in vertices:
            corner = course.corners.add()
            corner.latitude = latitude
            corner.longitude = longitude
        course.sent_at.GetCurrentTime()
        ensure_published(client, COURSE_TOPIC, course, retain=True)
        print(f"[COURSE] Published valid retained RxCourse on {COURSE_TOPIC}", flush=True)
        time.sleep(2)  # Let OCS receive and validate retained course before RunStart.

        command = rx_commands_pb2.RxCommand()
        command.team_id = TEAM
        command.seq = 1  # First simulated RoboCommand command in fresh gateway session.
        command.sent_at.GetCurrentTime()
        command.run_start.declaration_seq = int(box["declaration_seq"])
        command.run_start.run_id = int(time.time())  # Positive test run ID, avoids reuse across tests.
        ensure_published(client, CMD_TOPIC, command)
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
