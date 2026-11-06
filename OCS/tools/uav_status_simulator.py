#!/usr/bin/env python3
"""TEST/SIMULATED only 5 Hz UAV status publisher for the internal broker."""
import argparse, json, math, time
import paho.mqtt.client as mqtt

TOPIC = "/tongji_mrl/tsky/uav_status"
def main():
    p=argparse.ArgumentParser(); p.add_argument("--broker",default="127.0.0.1"); p.add_argument("--port",type=int,default=1884); p.add_argument("--duration",type=float,default=0.0); p.add_argument("--source-vehicle-id",default="UAV1"); p.add_argument("--malformed-once",action="store_true",help="publish one invalid JSON test message before valid samples"); p.add_argument("--wrong-vehicle-id",action="store_true",help="publish valid JSON with a deliberately wrong identity"); a=p.parse_args()
    c=mqtt.Client(mqtt.CallbackAPIVersion.VERSION2); c.connect(a.broker,a.port); c.loop_start(); end=time.monotonic()+a.duration if a.duration else None; i=0
    try:
      if a.malformed_once: c.publish(TOPIC,"{invalid TEST/SIMULATED JSON",qos=1)
      while end is None or time.monotonic()<end:
        value={"vehicle_id":"WRONG-UAV" if a.wrong_vehicle_id else a.source_vehicle_id,"vehicle_type":"uav","state":"AUTO","flight_phase":"AIRBORNE","position":{"latitude":1.2806+i*0.000001,"longitude":103.8557+i*0.000001},"altitude_hae_m":20.0,"spd_mps":4.0,"heading_deg":float((i*3)%360),"battery_status":{"connected":True,"remaining_percent":max(0,90-i/20),"voltage_v":22.2,"current_a":4.1,"time_remaining_s":1200-i,"warning":"TEST/SIMULATED"},"source_mode":"TEST/SIMULATED"}
        c.publish(TOPIC,json.dumps(value),qos=1); i+=1; time.sleep(.2)
    finally: c.disconnect(); c.loop_stop()
if __name__=='__main__': main()
