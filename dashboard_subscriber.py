import paho.mqtt.client as mqtt
import json
from datetime import datetime

def on_connect(client, userdata, flags, reason_code, properties):
    print("\n" + "=" * 60)
    print("  GRAND MARINA WATER MONITORING DASHBOARD")
    print("  Connected at:", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    print("=" * 60)
    client.subscribe("hydroficient/grandmarina/#")

def on_message(client, userdata, msg):
    try:
        data = json.loads(msg.payload.decode())
        display_reading(data)
    except json.JSONDecodeError:
        # Non-JSON message (maybe a command or alert)
        print(f"\n[RAW] {msg.topic}")
        print(f"      {msg.payload.decode()}")

def display_reading(data):
    """Format and display a sensor reading."""
    print(f"\n{'─' * 40}")
    print(f"  Location:  {data.get('location', 'Unknown')}")
    print(f"  Device ID: {data.get('device_id', 'Unknown')}")
    print(f"  Time:      {data.get('timestamp', 'N/A')}")
    print(f"  Count:     #{data.get('counter', 0)}")
    print(f"{'─' * 40}")

    # Pressure readings
    up = data.get('pressure_upstream', 0)
    down = data.get('pressure_downstream', 0)
    print(f"  Pressure (upstream):   {up:6.1f} PSI")
    print(f"  Pressure (downstream): {down:6.1f} PSI")

    # Pressure differential (can indicate blockage)
    diff = up - down
    print(f"  Pressure differential: {diff:6.1f} PSI")

    # Flow rate
    flow = data.get('flow_rate', 0)
    print(f"  Flow rate:             {flow:6.1f} gal/min")

# Create and configure client
client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
client.on_connect = on_connect
client.on_message = on_message

# Connect and run
print("Connecting to broker...")
client.connect("localhost", 1883)
client.loop_forever()
