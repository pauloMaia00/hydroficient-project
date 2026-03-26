"""
identity_tester.py - Identity Attack Simulation Tool

Tests various identity attack scenarios against your mTLS broker.
Use this to verify that your identity controls work correctly.

Usage:
    python identity_tester.py --mode test-correct
    python identity_tester.py --mode test-no-cert
    python identity_tester.py --mode test-wrong-ca
    python identity_tester.py --mode test-expired

Modes:
    test-correct   - Connect with valid client certificate (should succeed)
    test-no-cert   - Connect without any client certificate (should fail)
    test-wrong-ca  - Connect with cert signed by wrong CA (should fail)
    test-expired   - Connect with expired certificate (should fail)
"""

import paho.mqtt.client as mqtt
import ssl
import argparse
import sys
import time
import os

# Handle paho-mqtt 2.0+ API change
try:
    # paho-mqtt 2.0+
    MQTT_CLIENT_ARGS = {"callback_api_version": mqtt.CallbackAPIVersion.VERSION1}
except AttributeError:
    # paho-mqtt 1.x
    MQTT_CLIENT_ARGS = {}

# =============================================================================
# Configuration
# =============================================================================
BROKER_HOST = "localhost"
BROKER_PORT = 8883

# Certificate files
CA_CERT = "certs/ca.pem"
CLIENT_CERT = "certs/device-001.pem"
CLIENT_KEY = "certs/device-001-key.pem"

# For wrong CA test - you'll need to create these
WRONG_CA_CERT = "certs/wrong-ca.pem"
WRONG_CLIENT_CERT = "certs/wrong-device.pem"
WRONG_CLIENT_KEY = "certs/wrong-device-key.pem"

# For expired cert test - you'll need to create this
EXPIRED_CERT = "certs/expired-device.pem"
EXPIRED_KEY = "certs/expired-device-key.pem"


# =============================================================================
# Test Results
# =============================================================================
class TestResult:
    def __init__(self, name):
        self.name = name
        self.success = None
        self.error = None
        self.expected_outcome = None

    def record_success(self):
        self.success = True

    def record_failure(self, error):
        self.success = False
        self.error = str(error)

    def display(self):
        print("\n" + "=" * 60)
        print(f"TEST: {self.name}")
        print("=" * 60)
        print(f"Expected: {self.expected_outcome}")

        if self.success:
            outcome = "CONNECTION SUCCEEDED"
        else:
            outcome = "CONNECTION FAILED"

        print(f"Actual:   {outcome}")

        if self.error:
            print(f"Error:    {self.error}")

        # Determine if test passed
        if self.expected_outcome == "Connection rejected" and not self.success:
            print("\n>>> TEST PASSED - Connection was correctly rejected <<<")
            return True
        elif self.expected_outcome == "Connection succeeds" and self.success:
            print("\n>>> TEST PASSED - Connection succeeded as expected <<<")
            return True
        else:
            print("\n>>> TEST FAILED - Unexpected outcome! <<<")
            return False


# =============================================================================
# Connection Callback
# =============================================================================
connection_result = {"connected": False, "rc": -1}

def on_connect(client, userdata, flags, rc):
    global connection_result
    connection_result["connected"] = (rc == 0)
    connection_result["rc"] = rc


# =============================================================================
# Test Functions
# =============================================================================
def test_correct_cert():
    """Test with valid client certificate - should succeed."""
    print("\n" + "-" * 60)
    print("SCENARIO A: Correct Client Certificate")
    print("-" * 60)
    print("Testing connection with valid device-001 certificate...")

    result = TestResult("Valid Client Certificate")
    result.expected_outcome = "Connection succeeds"

    try:
        client = mqtt.Client(client_id="test-correct-cert", **MQTT_CLIENT_ARGS)
        client.on_connect = on_connect

        client.tls_set(
            ca_certs=CA_CERT,
            certfile=CLIENT_CERT,
            keyfile=CLIENT_KEY,
            cert_reqs=ssl.CERT_REQUIRED
        )

        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_start()
        time.sleep(2)  # Wait for connection
        client.loop_stop()

        if connection_result["connected"]:
            result.record_success()
        else:
            result.record_failure(f"Connection failed with rc={connection_result['rc']}")

        client.disconnect()

    except Exception as e:
        result.record_failure(e)

    return result.display()


def test_no_cert():
    """Test without client certificate - should fail."""
    print("\n" + "-" * 60)
    print("SCENARIO B: No Client Certificate")
    print("-" * 60)
    print("Testing connection WITHOUT any client certificate...")

    result = TestResult("No Client Certificate")
    result.expected_outcome = "Connection rejected"

    try:
        client = mqtt.Client(client_id="test-no-cert", **MQTT_CLIENT_ARGS)
        client.on_connect = on_connect

        # Only CA cert, NO client certificate - simulates rogue device
        client.tls_set(
            ca_certs=CA_CERT,
            cert_reqs=ssl.CERT_REQUIRED
        )

        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_start()
        time.sleep(2)
        client.loop_stop()

        if connection_result["connected"]:
            result.record_success()
        else:
            result.record_failure(f"Connection failed with rc={connection_result['rc']}")

        client.disconnect()

    except ssl.SSLError as e:
        result.record_failure(f"SSL Error: {e}")
    except Exception as e:
        result.record_failure(e)

    return result.display()


def test_wrong_ca():
    """Test with certificate from different CA - should fail."""
    print("\n" + "-" * 60)
    print("SCENARIO C: Certificate from Wrong CA")
    print("-" * 60)
    print("Testing connection with certificate signed by DIFFERENT CA...")

    result = TestResult("Wrong CA Certificate")
    result.expected_outcome = "Connection rejected"

    # Check if wrong CA files exist
    if not os.path.exists(WRONG_CLIENT_CERT):
        print(f"\nNOTE: {WRONG_CLIENT_CERT} not found.")
        print("To run this test, create a separate CA and sign a certificate with it.")
        print("This simulates an attacker who has their own CA but not yours.")
        result.record_failure("Test certificates not created - skipped")
        return result.display()

    try:
        client = mqtt.Client(client_id="test-wrong-ca", **MQTT_CLIENT_ARGS)
        client.on_connect = on_connect

        # Use cert signed by a different CA
        client.tls_set(
            ca_certs=CA_CERT,  # We still need to verify the broker
            certfile=WRONG_CLIENT_CERT,
            keyfile=WRONG_CLIENT_KEY,
            cert_reqs=ssl.CERT_REQUIRED
        )

        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_start()
        time.sleep(2)
        client.loop_stop()

        if connection_result["connected"]:
            result.record_success()
        else:
            result.record_failure(f"Connection failed with rc={connection_result['rc']}")

        client.disconnect()

    except ssl.SSLError as e:
        result.record_failure(f"SSL Error: {e}")
    except Exception as e:
        result.record_failure(e)

    return result.display()


def test_expired():
    """Test with expired certificate - should fail."""
    print("\n" + "-" * 60)
    print("SCENARIO D: Expired Certificate")
    print("-" * 60)
    print("Testing connection with EXPIRED client certificate...")

    result = TestResult("Expired Certificate")
    result.expected_outcome = "Connection rejected"

    # Check if expired cert files exist
    if not os.path.exists(EXPIRED_CERT):
        print(f"\nNOTE: {EXPIRED_CERT} not found.")
        print("To run this test, create a certificate with past expiration date.")
        print("Modify generate_client_certs.py: not_valid_after = datetime.now(timezone.utc) - timedelta(days=1)")
        result.record_failure("Expired certificate not created - skipped")
        return result.display()

    try:
        client = mqtt.Client(client_id="test-expired", **MQTT_CLIENT_ARGS)
        client.on_connect = on_connect

        client.tls_set(
            ca_certs=CA_CERT,
            certfile=EXPIRED_CERT,
            keyfile=EXPIRED_KEY,
            cert_reqs=ssl.CERT_REQUIRED
        )

        client.connect(BROKER_HOST, BROKER_PORT, keepalive=60)
        client.loop_start()
        time.sleep(2)
        client.loop_stop()

        if connection_result["connected"]:
            result.record_success()
        else:
            result.record_failure(f"Connection failed with rc={connection_result['rc']}")

        client.disconnect()

    except ssl.SSLError as e:
        result.record_failure(f"SSL Error: {e}")
    except Exception as e:
        result.record_failure(e)

    return result.display()


def run_all_tests():
    """Run all identity attack simulations."""
    print("=" * 60)
    print("IDENTITY ATTACK SIMULATION SUITE")
    print("The Grand Marina Hotel - mTLS Testing")
    print("=" * 60)

    results = []

    # Reset connection state
    global connection_result
    connection_result = {"connected": False, "rc": -1}

    # Run each test
    results.append(("A: Correct cert", test_correct_cert()))

    connection_result = {"connected": False, "rc": -1}
    results.append(("B: No cert", test_no_cert()))

    connection_result = {"connected": False, "rc": -1}
    results.append(("C: Wrong CA", test_wrong_ca()))

    connection_result = {"connected": False, "rc": -1}
    results.append(("D: Expired", test_expired()))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    for name, passed in results:
        status = "PASS" if passed else "FAIL"
        print(f"  {name}: {status}")

    passed_count = sum(1 for _, passed in results if passed)
    print(f"\n  Total: {passed_count}/{len(results)} tests passed")

    return all(passed for _, passed in results)


# =============================================================================
# Main
# =============================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Identity Attack Simulation Tool for mTLS Testing",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
    python identity_tester.py --mode test-correct
    python identity_tester.py --mode test-no-cert
    python identity_tester.py --mode all
        """
    )

    parser.add_argument(
        "--mode",
        choices=["test-correct", "test-no-cert", "test-wrong-ca", "test-expired", "all"],
        default="all",
        help="Test mode to run (default: all)"
    )

    args = parser.parse_args()

    # Map modes to functions
    mode_functions = {
        "test-correct": test_correct_cert,
        "test-no-cert": test_no_cert,
        "test-wrong-ca": test_wrong_ca,
        "test-expired": test_expired,
        "all": run_all_tests
    }

    if args.mode == "all":
        success = run_all_tests()
    else:
        print("=" * 60)
        print("IDENTITY ATTACK SIMULATION")
        print("=" * 60)
        success = mode_functions[args.mode]()

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()