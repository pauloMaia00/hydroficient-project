import paho.mqtt.client as mqtt
import json
import random
import time
import threading
import ssl   # ADD THIS FOR TLS
from datetime import datetime, timezone

class WaterSensorMQTT:
    """
    A water sensor that publishes readings to MQTT.
    """

    def __init__(self, device_id, location, broker="localhost", port=1883):
        self.device_id = device_id
        self.location = location
        self.counter = 0

        # MQTT setup
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
        self.client.connect(broker, port)
        self.client.loop_start()

        # Topic for this sensor
        self.topic = f"hydroficient/grandmarina/sensors/{self.location}/readings"

        # Base values for realistic variation
        self.base_pressure_up = 82
        self.base_pressure_down = 76
        self.base_flow = 40

    def get_reading(self):
        """Generate a sensor reading with realistic variation."""
        self.counter += 1
        return {
            "device_id": self.device_id,  # identity
            "location": self.location,    # context (optional but recommended)
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "counter": self.counter,
            "pressure_upstream": round(self.base_pressure_up + random.uniform(-2, 2), 1),
            "pressure_downstream": round(self.base_pressure_down + random.uniform(-2, 2), 1),
            "flow_rate": round(self.base_flow + random.uniform(-3, 3), 1)
        }
    
    def get_leak_reading(self):
        """
        Generate a reading simulating a water leak 

        A leak causes abnormally HIGH flow rate (80-120 gallons/min)

        Returns: 
            dict: Sensor reading with anomalous high flow rate
        """
        self.counter += 1
        return {
            "device_id": self.device_id,
            "location": self.location,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "counter": self.counter,
            "pressure_upstream": round(self.base_pressure_up + random.uniform(-2, 2), 1),
            "pressure_downstream": round(self.base_pressure_down + random.uniform(-5, 0), 1),
            "flow_rate": round(random.uniform(80, 120), 1) #Abnormally high
        }
    
    def get_blockage_reading(self):
        """
        Generate a reading simulating a pipe blocking. 

        A blockage causes HIGH upstream pressure and LOW downstream pressure.

        Returns:
            dict: Sensor reading with pressure differential indicating blockage
        """
        self.counter += 1
        return{
            "device_id": self.device_id,
            "location": self.location,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "counter": self.counter,
            "pressure_upstream": round(random.uniform(95, 110), 1), # High 
            "pressure_downstream": round(random.uniform(50, 60), 1), # Low
            "flow_rate": round(random.uniform(10, 20), 1) #Reduced flow
        }

    def publish_reading(self):
        """
        Generate a reading and publish it to MQTT.

        Returns:
            dict: The readings that was published
        """
        reading = self.get_reading()
        self.client.publish(self.topic, json.dumps(reading))
        return reading

    def run_continuous(self, interval=2):
        """Publish readings continuously at the specified interval."""
        print(f"Starting device: {self.device_id}")
        print(f"Location: {self.location}")
        print(f"Publishing to: {self.topic}")
        print(f"Interval: {interval} seconds")
        print("-" * 40)

        try:
            while True:
                reading = self.publish_reading()
                print(f"[{reading['counter']}] Pressure: {reading['pressure_upstream']}/{reading['pressure_downstream']} PSI, Flow: {reading['flow_rate']} gal/min")
                time.sleep(interval)
        except KeyboardInterrupt:
            print("\nSensor stopped.")
            self.client.loop_stop()
            self.client.disconnect()

def run_sensor(device_id, location, interval):
    sensor = WaterSensorMQTT(device_id=device_id, location=location)
    sensor.run_continuous(interval)

# Example usage when run directly
if __name__=="__main__":
    devices = [
        {"device_id": "GM-HYDROLOGIC-01", "location": "main-building"},
        {"device_id": "GM-HYDROLOGIC-02", "location": "pool-wing"},
        {"device_id": "GM-HYDROLOGIC-03", "location": "kitchen"},
    ]

    threads = []
    for d in devices:
        t = threading.Thread(target=run_sensor, args=(d["device_id"], d["location"], 2), daemon=True)
        t.start()
        threads.append(t)

    print("All sensors running. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print("\nStopping all sensors.")