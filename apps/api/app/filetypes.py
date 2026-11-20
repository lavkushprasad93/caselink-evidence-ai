from pathlib import PurePosixPath

ALLOWED: dict[str, set[str]] = {
    "pdf": {".pdf"},
    "jpeg": {".jpg", ".jpeg"},
    "png": {".png"},
    "tiff": {".tif", ".tiff"},
}
CONTENT_TYPES = {
    "pdf": "application/pdf",
    "jpeg": "image/jpeg",
    "png": "image/png",
    "tiff": "image/tiff",
}


def safe_filename(filename: str | None) -> str:
    name = (filename or "").replace("\\", "/").rsplit("/", maxsplit=1)[-1]
    name = "".join(char for char in name if char.isprintable() and char not in "/\\")
    if name in {"", ".", ".."}:
        return "upload"
    return name


def extension_of(filename: str) -> str:
    return PurePosixPath(filename).suffix.lower()


def sniff_type(header: bytes) -> str | None:
    if header.startswith(b"%PDF-"):
        return "pdf"
    if header.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if header.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if header.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    return None
