from email.message import EmailMessage

import pytest
from app.parsers import PermanentParseError, chunk_segments, parse_bytes


def test_markdown_keeps_line_locators():
    segments = parse_bytes("journal.md", b"# Heading\n\nShipment DEMO-1 cleared.\n")
    assert [item.locator for item in segments] == ["line 1", "line 3"]
    assert "DEMO-1" in segments[1].text


def test_email_body_is_parsed_without_loading_external_content():
    message = EmailMessage()
    message["Subject"] = "Status update"
    message.set_content("Package is ready for dispatch.")
    segments = parse_bytes("message.eml", message.as_bytes())
    assert any(item.locator == "email body" for item in segments)
    assert any("Status update" in item.text for item in segments)


def test_unsupported_type_is_rejected():
    with pytest.raises(PermanentParseError):
        parse_bytes("macro.xlsm", b"not safe")


def test_chunking_never_crosses_segment_boundary():
    from app.parsers import Segment

    chunks = chunk_segments(
        [Segment("page 1", "one two three four"), Segment("page 2", "five six")],
        max_words=3,
        overlap=1,
    )
    assert len(chunks) == 3
    assert chunks[-1].locator == "page 2"
