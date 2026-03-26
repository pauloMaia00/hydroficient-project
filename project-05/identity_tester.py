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
from pathlib import Path
from datetime import datetime, timedelta, timezone

try:
    from cryptography import x509
    from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
except ImportError:
    x509 = None

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
CA_KEY = "certs/ca-key.pem"   # needed to sign the expired client cert
CLIENT_CERT = "certs/device-001.pem"
CLIENT_KEY = "certs/device-001-key.pem"

# For wrong CA test - you'll need to create these
WRONG_CA_CERT = "certs/wrong-ca.pem"
WRONG_CA_KEY = "certs/wrong-ca-key.pem"
WRONG_CLIENT_CERT = "certs/wrong-device.pem"
WRONG_CLIENT_KEY = "certs/wrong-device-key.pem"

# For expired cert test - you'll need to create this
EXPIRED_CERT = "certs/expired-device.pem"
EXPIRED_KEY = "certs/expired-device-key.pem"

# =============================================================================
# Certificate Generation Helpers
# =============================================================================

def require_cryptography():
    if x509 is None:
        raise RuntimeError(
            "The 'cryptography' package is required to generate test certificates.\n"
            "Install it with: pip install cryptography"
        )

def ensure_certs_dir():
    Path("certs").mkdir(parents=True, exist_ok=True)

def write_private_key(path, key):
    with open(path, "wb") as f:
        f.write(
            key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.TraditionalOpenSSL,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )

def write_certificate(path, cert):
    with open(path, "wb") as f:
        f.write(cert.public_bytes(serialization.Encoding.PEM))

def generate_private_key():
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)

def build_name(common_name):
    return x509.Name([
        x509.NameAttribute(NameOID.COUNTRY_NAME, "US"),
        x509.NameAttribute(NameOID.STATE_OR_PROVINCE_NAME, "Virginia"),
        x509.NameAttribute(NameOID.LOCALITY_NAME, "Charlottesville"),
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Grand Marina Test Lab"),
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])

def generate_self_signed_ca(common_name, valid_days=365):
    key = generate_private_key()
    subject = issuer = build_name(common_name)
    now = datetime.now(timezone.utc)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(days=1))
        .not_valid_after(now + timedelta(days=valid_days))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(key, hashes.SHA256())
    )

    return key, cert

def generate_client_cert_signed_by_ca(common_name, ca_cert, ca_key, valid_from, valid_to):
    key = generate_private_key()
    subject = build_name(common_name)

    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(ca_cert.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(valid_from)
        .not_valid_after(valid_to)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.CLIENT_AUTH]),
            critical=False
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()),
            critical=False
        )
        .sign(ca_key, hashes.SHA256())
    )

    return key, cert

def load_pem_private_key_from_file(path):
    with open(path, "rb") as f:
        return serialization.load_pem_private_key(f.read(), password=None)

def load_pem_certificate_from_file(path):
    with open(path, "rb") as f:
        return x509.load_pem_x509_certificate(f.read())

def ensure_wrong_ca_materials():
    """
    Creates:
      - wrong-ca.pem / wrong-ca-key.pem
      - wrong-device.pem / wrong-device-key.pem
    These are used to simulate a client cert signed by an untrusted CA.
    """
    require_cryptography()
    ensure_certs_dir()

    if os.path.exists(WRONG_CLIENT_CERT) and os.path.exists(WRONG_CLIENT_KEY):
        return

    wrong_ca_key, wrong_ca_cert = generate_self_signed_ca("Wrong Test CA", valid_days=365)

    now = datetime.now(timezone.utc)
    wrong_client_key, wrong_client_cert = generate_client_cert_signed_by_ca(
        common_name="wrong-device",
        ca_cert=wrong_ca_cert,
        ca_key=wrong_ca_key,
        valid_from=now - timedelta(days=1),
        valid_to=now + timedelta(days=30),
    )

    write_private_key(WRONG_CA_KEY, wrong_ca_key)
    write_certificate(WRONG_CA_CERT, wrong_ca_cert)
    write_private_key(WRONG_CLIENT_KEY, wrong_client_key)
    write_certificate(WRONG_CLIENT_CERT, wrong_client_cert)

def ensure_expired_cert_materials():
    """
    Creates:
      - expired-device.pem / expired-device-key.pem
    IMPORTANT:
      This expired client cert is signed by the REAL CA so the broker
      rejects it specifically because it is expired, not because it is untrusted.
    """
    require_cryptography()
    ensure_certs_dir()

    if os.path.exists(EXPIRED_CERT) and os.path.exists(EXPIRED_KEY):
        return

    if not os.path.exists(CA_CERT):
        raise FileNotFoundError(f"Real CA certificate not found: {CA_CERT}")

    if not os.path.exists(CA_KEY):
        raise FileNotFoundError(
            f"Real CA private key not found: {CA_KEY}\n"
            "The expired certificate must be signed by your real CA."
        )

    real_ca_cert = load_pem_certificate_from_file(CA_CERT)
    real_ca_key = load_pem_private_key_from_file(CA_KEY)

    now = datetime.now(timezone.utc)

    expired_key, expired_cert = generate_client_cert_signed_by_ca(
        common_name="expired-device",
        ca_cert=real_ca_cert,
        ca_key=real_ca_key,
        valid_from=now - timedelta(days=30),
        valid_to=now - timedelta(days=1),  # already expired
    )

    write_private_key(EXPIRED_KEY, expired_key)
    write_certificate(EXPIRED_CERT, expired_cert)

def reset_connection_result():
    global connection_result
    connection_result = {"connected": False, "rc": -1}


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

    reset_connection_result()

    result = TestResult("Wrong CA Certificate")
    result.expected_outcome = "Connection rejected"

    try:
        ensure_wrong_ca_materials()

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

    reset_connection_result()

    result = TestResult("Expired Certificate")
    result.expected_outcome = "Connection rejected"

   
    try:
        ensure_expired_cert_materials()
        
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