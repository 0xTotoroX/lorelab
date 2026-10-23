from soota.secrets import REDACTED, redact_any, redact_text, redact_url


def test_redact_bearer_and_signed_url() -> None:
    text = "Authorization: Bearer Example0003lmnop"
    assert "Example0003lmnop" not in redact_text(text)
    url = "https://googlevideo.com/videoplayback?expire=1&sig=SECRET123"
    redacted = redact_url(url)
    assert "SECRET123" not in redacted
    payload = redact_any({"Authorization": "Bearer Example0003lmnop", "url": url})
    assert payload["Authorization"] == REDACTED
    assert "SECRET" not in str(payload)
