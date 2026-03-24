import argparse
import json
import os
import ssl
import statistics
import subprocess
import sys
import threading
import time
import uuid

import paho.mqtt.client as mqtt


class ExperimentRunner:
    def __init__(self, args):
        self.args = args
        self.host = args.host
        self.tls_enabled = args.tls.lower() == "on"
        self.port = 8883 if self.tls_enabled else 1883
        if args.mode == "test-wrong-ca":
            self.ca_path = "certs/wrong-ca.pem"
        else:
            self.ca_path = args.ca_path

        self.topic_base = args.topic
        self.client_id = f"experiment-runner-{uuid.uuid4().hex[:8]}"
        self.client = mqtt.Client(
            callback_api_version=mqtt.CallbackAPIVersion.VERSION1,
            client_id=self.client_id,
            protocol=mqtt.MQTTv311,
        )

        self.connected_event = threading.Event()
        self.subscribed_event = threading.Event()
        self.received_event = threading.Event()

        self.connection_error = None
        self.latencies = []
        self.sent_times = {}
        self.received_count = 0
        self.stress_topic = f"{self.topic_base}/stress/{uuid.uuid4().hex[:6]}"
        self.latency_topic = f"{self.topic_base}/latency/{uuid.uuid4().hex[:6]}"

        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_subscribe = self.on_subscribe
        self.client.on_disconnect = self.on_disconnect

        if self.tls_enabled:
            self.configure_tls()

    def configure_tls(self):
        if self.args.no_ca:
            self.client.tls_set(
                cert_reqs=ssl.CERT_NONE,
                tls_version=ssl.PROTOCOL_TLS,
            )
            self.client.tls_insecure_set(True)
            return

        if not os.path.exists(self.ca_path):
            raise FileNotFoundError(f"CA certificate not found: {self.ca_path}")

        self.client.tls_set(
            ca_certs=self.ca_path,
            cert_reqs=ssl.CERT_REQUIRED,
            tls_version=ssl.PROTOCOL_TLS,
    )

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected_event.set()
        else:
            self.connection_error = f"Connection failed with rc={rc}"
            self.connected_event.set()

    def on_disconnect(self, client, userdata, rc):
        pass

    def on_subscribe(self, client, userdata, mid, granted_qos):
        self.subscribed_event.set()

    def on_message(self, client, userdata, msg):
        self.received_count += 1

        try:
            payload = json.loads(msg.payload.decode())
            msg_id = payload.get("id")
            sent_ts = payload.get("sent_ts")

            if sent_ts is not None:
                latency_ms = (time.time() - sent_ts) * 1000
                self.latencies.append(latency_ms)

            if msg_id in self.sent_times:
                self.received_event.set()

        except Exception:
            pass

    def connect(self):
        self.client.connect(self.host, self.port, keepalive=60)
        self.client.loop_start()

        if not self.connected_event.wait(timeout=5):
            self.client.loop_stop()
            raise TimeoutError("Timed out waiting for broker connection.")

        if self.connection_error:
            self.client.loop_stop()
            raise ConnectionError(self.connection_error)

    def disconnect(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception:
            pass

    def print_header(self, title, extra_lines=None):
        print("=" * 50)
        print(f"  {title}")
        if extra_lines:
            for line in extra_lines:
                print(f"  {line}")
        print("=" * 50)
        print()

    def run_publish(self):
        count = self.args.count

        self.print_header(
            "Publish Test",
            [
                f"TLS: {'ON' if self.tls_enabled else 'OFF'}",
                f"Messages: {count}",
            ],
        )

        self.connect()
        topic = f"{self.topic_base}/sensors/test-location/readings"

        for i in range(1, count + 1):
            payload = {
                "device_id": "test-sensor-001",
                "pressure_psi": 81.5 + i,
                "flow_gpm": 40.0 + i,
                "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
                "reading_num": i
            }
            self.client.publish(topic, json.dumps(payload))
            print(f"  Published {i}/{count}")
            time.sleep(1)

        print()
        print("=" * 50)
        print(f"  Publish Complete (TLS {'ON' if self.tls_enabled else 'OFF'})")
        print("=" * 50)

        self.disconnect()

    def run_connect(self):
        ca_label = "NONE" if self.args.no_ca else self.ca_path

        self.print_header(
            "Connection Test",
            [
                f"TLS: {'ON' if self.tls_enabled else 'OFF'}",
                f"CA Certificate: {ca_label}",
            ],
        )

        try:
            self.connect()
            print("  Connection successful.")
        except Exception as e:
            print(f"  Connection failed: {e}")
        finally:
            self.disconnect()

    def run_test_wrong_ca(self):
        ca_label = self.ca_path

        self.print_header(
            "Connection Test",
            [
                "TLS: ON",
                f"CA Certificate: {ca_label}",
            ],
        )

        try:
            self.connect()
            print("SUCCESS: Connected to broker!")
        except Exception as e:
            print(f"FAILED: {e}")
        finally:
            self.disconnect()

    def run_latency(self):
        count = self.args.count

        self.print_header(
            "Latency Test",
            [
                f"TLS: {'ON' if self.tls_enabled else 'OFF'}",
                f"Messages: {count}",
            ],
        )

        self.connect()

        self.client.subscribe(self.latency_topic, qos=0)
        if not self.subscribed_event.wait(timeout=3):
            raise TimeoutError("Timed out waiting for subscription.")

        for i in range(1, count + 1):
            self.received_event.clear()

            payload = {
                "id": i,
                "sent_ts": time.time(),
                "message": f"latency test {i}",
            }

            self.sent_times[i] = payload["sent_ts"]
            self.client.publish(self.latency_topic, json.dumps(payload), qos=0)

            if not self.received_event.wait(timeout=2):
                print(f"  Warning: message {i} not received within timeout.")

            if i % 10 == 0 or i == count:
                print(f"  Sent {i}/{count} messages...")

        print()

        if self.latencies:
            avg_latency = statistics.mean(self.latencies)
            min_latency = min(self.latencies)
            max_latency = max(self.latencies)
            std_latency = statistics.stdev(self.latencies) if len(self.latencies) > 1 else 0.0
        else:
            avg_latency = min_latency = max_latency = std_latency = 0.0

        print("=" * 50)
        print(f"  Latency Results (TLS {'ON' if self.tls_enabled else 'OFF'})")
        print("=" * 50)
        print(f"  Messages sent: {count}")
        print(f"  Average latency: {avg_latency:.2f} ms")
        print(f"  Min latency: {min_latency:.2f} ms")
        print(f"  Max latency: {max_latency:.2f} ms")
        print(f"  Std deviation: {std_latency:.2f} ms")
        print("=" * 50)

        self.disconnect()

    def run_stress(self):
        rate = self.args.rate
        duration = self.args.duration
        total_messages = rate * duration

        self.print_header(
            "Stress Test",
            [
                f"TLS: {'ON' if self.tls_enabled else 'OFF'}",
                f"Rate: {rate} msg/sec",
                f"Duration: {duration} sec",
            ],
        )

        self.connect()

        interval = 1.0 / rate
        start_time = time.time()

        successful_publishes = 0
        error_count = 0

        for i in range(1, total_messages + 1):
            payload = {
                "id": i,
                "timestamp": time.time(),
                "message": f"stress test {i}",
            }
            result = self.client.publish(self.stress_topic, json.dumps(payload), qos=0)

            if result.rc == mqtt.MQTT_ERR_SUCCESS:
                successful_publishes += 1
            else:
                error_count += 1
                print(f"  Error publishing message {i}: rc={result.rc}")


            next_send = start_time + (i * interval)
            sleep_time = next_send - time.time()
            if sleep_time > 0:
                time.sleep(sleep_time)

            if i % rate == 0 or i == total_messages:
                print(f"  Sent {i}/{total_messages} messages...")

        elapsed = time.time() - start_time

        actual_rate = successful_publishes / elapsed if elapsed > 0 else 0
        success_rate = (successful_publishes / total_messages) * 100 if total_messages > 0 else 0

        if actual_rate >= rate:
            status = "SUCCESS"
        else:
            status = "DEGRADED"

        print()
        print("=" * 50)
        print(f"  Stress Results (TLS {'ON' if self.tls_enabled else 'OFF'})")
        print("=" * 50)
        print(f"  Target rate: {rate:.2f} msg/sec")
        print(f"  Actual rate: {actual_rate:.2f} msg/sec")
        print(f"  Messages sent: {total_messages}")
        print(f"Errors: {error_count}")
        print(f"  Success rate: {success_rate:.2f}%")
        print(f"  Actual elapsed time: {elapsed:.2f} sec")
        print(f"  Status: {status}")
        print("=" * 50)

        self.disconnect()

    def run_generate_expired_cert(self):
        self.print_header("Generate Expired Cert")

        certs_dir = "certs"
        os.makedirs(certs_dir, exist_ok=True)

        key_path = os.path.join(certs_dir, "expired-client.key")
        csr_path = os.path.join(certs_dir, "expired-client.csr")
        cert_path = os.path.join(certs_dir, "expired-client.crt")

        print("  Attempting to generate a certificate for expired-cert testing.")
        print("  This requires OpenSSL to be installed and available in PATH.")
        print()

        commands = [
            ["openssl", "genrsa", "-out", key_path, "2048"],
            [
                "openssl", "req", "-new", "-key", key_path,
                "-out", csr_path,
                "-subj", "/CN=expired-client"
            ],
            [
                "openssl", "x509", "-req",
                "-in", csr_path,
                "-signkey", key_path,
                "-out", cert_path,
                "-days", "0"
            ],
        ]

        try:
            for cmd in commands:
                subprocess.run(cmd, check=True)
            print(f"  Created key: {key_path}")
            print(f"  Created cert: {cert_path}")
            print("  Note: -days 0 may create a cert that expires immediately.")
        except FileNotFoundError:
            print("  OpenSSL was not found on this system.")
            print("  Install OpenSSL or create the expired cert manually.")
        except subprocess.CalledProcessError as e:
            print(f"  Failed to generate expired cert: {e}")

    def run_generate_wrong_ca(self):
        self.print_header("Generate Wrong CA")

        certs_dir = "certs"
        os.makedirs(certs_dir, exist_ok=True)

        wrong_ca_key = os.path.join(certs_dir, "wrong-ca.key")
        wrong_ca_pem = os.path.join(certs_dir, "wrong-ca.pem")

        print("  Attempting to generate a mismatched CA for wrong-CA testing.")
        print("  This requires OpenSSL to be installed and available in PATH.")
        print()

        commands = [
            ["openssl", "genrsa", "-out", wrong_ca_key, "2048"],
            [
                "openssl", "req", "-x509", "-new", "-nodes",
                "-key", wrong_ca_key,
                "-sha256",
                "-days", "365",
                "-out", wrong_ca_pem,
                "-subj", "/CN=wrong-ca"
            ],
        ]

        try:
            for cmd in commands:
                subprocess.run(cmd, check=True)
            print(f"  Created mismatched CA file: {wrong_ca_pem}")
        except FileNotFoundError:
            print("  OpenSSL was not found on this system.")
            print("  Install OpenSSL or create the mismatched CA manually.")
        except subprocess.CalledProcessError as e:
            print(f"  Failed to generate wrong CA: {e}")

    def run(self):
        if self.args.mode == "publish":
            self.run_publish()
        elif self.args.mode == "connect":
            self.run_connect()
        elif self.args.mode == "latency":
            self.run_latency()
        elif self.args.mode == "stress":
            self.run_stress()
        elif self.args.mode == "generate-expired-cert":
            self.run_generate_expired_cert()
        elif self.args.mode == "generate-wrong-ca":
            self.run_generate_wrong_ca()
        elif self.args.mode == "test-wrong-ca":
            self.run_test_wrong_ca()
        else:
            raise ValueError(f"Unknown mode: {self.args.mode}")


def build_parser():
    parser = argparse.ArgumentParser(description="MQTT experiment runner")
    parser.add_argument(
        "--mode",
        required=True,
        choices=[
            "publish",
            "connect",
            "latency",
            "stress",
            "generate-expired-cert",
            "generate-wrong-ca",
            "test-wrong-ca",
        ],
        help="Experiment mode to run",
    )
    parser.add_argument(
        "--tls",
        default="off",
        choices=["on", "off"],
        help="Enable or disable TLS",
    )
    parser.add_argument(
        "--host",
        default="localhost",
        help="MQTT broker host",
    )
    parser.add_argument(
        "--topic",
        default="hydroficient/grandmarina/",
        help="Base MQTT topic",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=10,
        help="Number of messages for publish/latency tests",
    )
    parser.add_argument(
        "--rate",
        type=int,
        default=25,
        help="Messages per second for stress test",
    )
    parser.add_argument(
        "--duration",
        type=int,
        default=30,
        help="Duration in seconds for stress test",
    )
    parser.add_argument(
        "--ca-path",
        default="certs/ca.pem",
        help="Path to CA certificate",
    )
    parser.add_argument(
        "--no-ca",
        action="store_true",
        help="Do not load the CA certificate (used for negative TLS tests)",
    )
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()

    try:
        runner = ExperimentRunner(args)
        runner.run()
    except Exception as e:
        print(f"Error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()