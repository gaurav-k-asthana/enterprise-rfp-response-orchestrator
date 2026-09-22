from io import BytesIO
from zipfile import ZipFile, ZipInfo

from scripts.build_step_5_11_qa import _docx_package_members


def _package(*, timestamp: tuple[int, int, int, int, int, int], body: bytes) -> bytes:
    buffer = BytesIO()
    with ZipFile(buffer, "w") as package:
        member = ZipInfo("word/document.xml", date_time=timestamp)
        package.writestr(member, body)
    return buffer.getvalue()


def test_logical_docx_comparison_ignores_zip_container_timestamps() -> None:
    first = _package(timestamp=(2026, 9, 16, 13, 25, 8), body=b"<document />")
    second = _package(timestamp=(2026, 9, 22, 12, 44, 18), body=b"<document />")

    assert first != second
    assert _docx_package_members(first) == _docx_package_members(second)


def test_logical_docx_comparison_detects_member_content_drift() -> None:
    first = _package(timestamp=(2026, 9, 16, 13, 25, 8), body=b"<document />")
    changed = _package(timestamp=(2026, 9, 22, 12, 44, 18), body=b"<changed />")

    assert _docx_package_members(first) != _docx_package_members(changed)
