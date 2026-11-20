import socket
import struct
from typing import Any, Self

import pytest

from app.config import settings
from app.scanner import ClamAVScanner, ScannerUnavailable

EICAR = b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR-STANDARD-ANTIVIRUS-TEST-FILE!$H+H*"


class FakeSocket:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.sent: list[bytes] = []
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *_args: object) -> None:
        self.closed = True

    def sendall(self, data: bytes) -> None:
        self.sent.append(data)

    def recv(self, _size: int) -> bytes:
        response, self.response = self.response, b""
        return response


def scanner_with_reply(
    monkeypatch: pytest.MonkeyPatch, reply: bytes
) -> tuple[ClamAVScanner, FakeSocket]:
    fake = FakeSocket(reply)
    monkeypatch.setattr(socket, "create_connection", lambda *_args, **_kwargs: fake)
    return ClamAVScanner("clamav", 3310), fake


def test_scanner_streams_chunks_and_accepts_clean_reply(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scanner, fake = scanner_with_reply(monkeypatch, b"stream: OK\0")

    assert scanner.scan([b"abc", b"def"]) is None
    assert fake.sent == [
        b"zINSTREAM\0",
        struct.pack("!I", 3) + b"abc",
        struct.pack("!I", 3) + b"def",
        struct.pack("!I", 0),
    ]
    assert fake.closed


def test_scanner_returns_detected_signature(monkeypatch: pytest.MonkeyPatch) -> None:
    scanner, _fake = scanner_with_reply(monkeypatch, b"stream: Eicar-Signature FOUND\0")

    assert scanner.scan([b"sample"]) == "Eicar-Signature"


def test_scanner_rejects_error_reply(monkeypatch: pytest.MonkeyPatch) -> None:
    scanner, _fake = scanner_with_reply(monkeypatch, b"stream: ERROR\0")

    with pytest.raises(ScannerUnavailable, match="returned an error"):
        scanner.scan([b"sample"])


def test_scanner_maps_connection_errors_to_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_connect(*_args: Any, **_kwargs: Any) -> None:
        raise OSError("connection refused")

    monkeypatch.setattr(socket, "create_connection", fail_connect)
    scanner = ClamAVScanner("clamav", 3310)

    with pytest.raises(ScannerUnavailable, match="unavailable"):
        scanner.scan([b"sample"])


def test_live_clamav_detects_eicar() -> None:
    scanner = ClamAVScanner(settings.clamav_host, settings.clamav_port, timeout=5)
    try:
        verdict = scanner.scan([EICAR])
    except ScannerUnavailable:
        pytest.skip("ClamAV not reachable")
    assert verdict is not None
