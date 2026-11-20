import pytest

from app.filetypes import extension_of, safe_filename, sniff_type


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        (b"%PDF-1.7", "pdf"),
        (b"\xff\xd8\xff\xe0", "jpeg"),
        (b"\x89PNG\r\n\x1a\n", "png"),
        (b"II*\x00", "tiff"),
        (b"MM\x00*", "tiff"),
        (b"MZ\x90\x00", None),
        (b"", None),
    ],
)
def test_sniff_type_uses_file_signature(header: bytes, expected: str | None) -> None:
    assert sniff_type(header) == expected


def test_extensions_are_case_insensitive() -> None:
    assert extension_of("document.PDF") == ".pdf"
    assert extension_of("photo.JPEG") == ".jpeg"


def test_safe_filename_discards_path_components_and_controls() -> None:
    assert safe_filename("../../etc/passwd.pdf") == "passwd.pdf"
    assert safe_filename(r"..\..\secret.png") == "secret.png"
    assert safe_filename("bad\x00name.pdf") == "badname.pdf"
    assert safe_filename(None) == "upload"
