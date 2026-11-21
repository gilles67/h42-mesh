"""A local HTTPS server with a test certificate authority."""

import datetime
import http.server
import json
import ssl
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID


def _name(common_name: str) -> x509.Name:
    return x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, common_name)])


def make_certificates(directory: Path, server_name: str) -> tuple[Path, Path, Path]:
    """(ca.pem, server.pem, server.key) for ``server_name``."""
    now = datetime.datetime.now(datetime.UTC)
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = (
        x509.CertificateBuilder()
        .subject_name(_name("h42 test CA"))
        .issuer_name(_name("h42 test CA"))
        .public_key(ca_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=True,
                crl_sign=True,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .sign(ca_key, hashes.SHA256())
    )
    key = ec.generate_private_key(ec.SECP256R1())
    certificate = (
        x509.CertificateBuilder()
        .subject_name(_name(server_name))
        .issuer_name(ca.subject)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(days=1))
        .not_valid_after(now + datetime.timedelta(days=1))
        .add_extension(x509.SubjectAlternativeName([x509.DNSName(server_name)]), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(key.public_key()), critical=False)
        .sign(ca_key, hashes.SHA256())
    )
    ca_path, cert_path, key_path = (directory / n for n in ("ca.pem", "server.pem", "server.key"))
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))
    cert_path.write_bytes(certificate.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    return ca_path, cert_path, key_path


@dataclass
class Recorded:
    """What the server saw, and what it answers."""

    requests: list[dict[str, Any]] = field(default_factory=list)
    server_names: list[str | None] = field(default_factory=list)
    status: int = 200
    body: dict[str, Any] = field(default_factory=lambda: {"ok": True})


@contextmanager
def https_server(directory: Path, server_name: str) -> Iterator[tuple[int, Path, Recorded]]:
    """Yields (port, CA file, record) of a server on 127.0.0.1."""
    ca_path, cert_path, key_path = make_certificates(directory, server_name)
    recorded = Recorded()

    class Handler(http.server.BaseHTTPRequestHandler):
        def _answer(self) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            recorded.requests.append(
                {
                    "method": self.command,
                    "path": self.path,
                    "headers": {k.lower(): v for k, v in self.headers.items()},
                    "body": self.rfile.read(length) if length else b"",
                }
            )
            data = json.dumps(recorded.body).encode()
            self.send_response(recorded.status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("ETag", '"etag-value"')
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_POST = do_PUT = _answer  # noqa: N815 (names of http.server)

        def log_message(self, format: str, *args: Any) -> None:
            pass

    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(cert_path, key_path)

    def sni(sock: ssl.SSLObject, name: str | None, ctx: ssl.SSLContext) -> None:
        recorded.server_names.append(name)

    context.sni_callback = sni
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1], ca_path, recorded
    finally:
        server.shutdown()
        server.server_close()
