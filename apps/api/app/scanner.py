"""ClamAV client using clamd's INSTREAM protocol."""

import socket
import struct
from collections.abc import Iterable
from typing import Protocol

from app.config import settings


class ScannerUnavailable(Exception):
    """The scanner could not give a verdict; callers must reject the upload."""


class Scanner(Protocol):
    def scan(self, chunks: Iterable[bytes]) -> str | None:
        """Return None if clean, or the signature name if malware was found."""
        ...


class ClamAVScanner:
    def __init__(self, host: str, port: int, timeout: float = 30.0) -> None:
        self.host, self.port, self.timeout = host, port, timeout

    def scan(self, chunks: Iterable[bytes]) -> str | None:
        try:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.sendall(b"zINSTREAM\0")
                for chunk in chunks:
                    if chunk:
                        sock.sendall(struct.pack("!I", len(chunk)) + chunk)
                sock.sendall(struct.pack("!I", 0))
                reply = self._read_reply(sock)
        except OSError as exc:
            raise ScannerUnavailable("ClamAV is unavailable") from exc

        if reply.endswith("OK"):
            return None
        if reply.endswith("FOUND"):
            return reply.removeprefix("stream:").removesuffix("FOUND").strip() or "unknown"
        raise ScannerUnavailable(f"ClamAV returned an error: {reply}")

    @staticmethod
    def _read_reply(sock: socket.socket) -> str:
        data = bytearray()
        while not data.endswith(b"\0"):
            part = sock.recv(4096)
            if not part:
                break
            data.extend(part)
        return data.rstrip(b"\0").decode("utf-8", "replace").strip()


def get_scanner() -> Scanner:
    return ClamAVScanner(settings.clamav_host, settings.clamav_port)
