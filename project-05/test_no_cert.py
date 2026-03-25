# test_no_cert.py - Should be REJECTED
import paho.mqtt.client as mqtt
import ssl

# Handle paho-mqtt 2.0+ API change
try:
    MQTT_CLIENT_ARGS = {"callback_api_version": mqtt.CallbackAPIVersion.VERSION1}
except AttributeError:
    MQTT_CLIENT_ARGS = {}

client = mqtt.Client(client_id="rogue-device", **MQTT_CLIENT_ARGS)

# Only CA cert, NO client certificate
client.tls_set(ca_certs="certs/ca.pem")

try:
    client.connect("localhost", 8883, keepalive=60)
    print("ERROR: Connection should have been rejected!")
except Exception as e:
    print(f"SUCCESS: Connection rejected: {e}")