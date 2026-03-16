import ipaddress 
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography import x509
from cryptography.x509.oid import NameOID
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa

def generate_ca_certificate():
    """Generate the Certificate Authority (CA) certificate"""

    # Step 1: Generate a private key for the CA
    ca_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048
    )

        # Step 2: Define the CA's identity
    ca_name = x509.Name([
        x509.NameAttribute(NameOID.ORGANIZATION_NAME, "Grand Marina Hotel"),
        x509.NameAttribute(NameOID.ORGANIZATIONAL_UNIT_NAME, "Water Systems Security"),
        x509.NameAttribute(NameOID.COMMON_NAME, "Grand Marina Root CA"),
    ])

        # Step 3: Build and sign the CA certificate
    ca_cert = (
        x509.CertificateBuilder()
        .subject_name(ca_name)
        .issuer_name(ca_name)  # Self-signed: issuer = subject
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(datetime.now(timezone.utc))
        .not_valid_after(datetime.now(timezone.utc) + timedelta(days=3650))
        .add_extension(
            x509.BasicConstraints(ca=True, path_length=None),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )