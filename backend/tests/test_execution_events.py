from nexus.observability.tracing import redact_trace_payload


def test_trace_payload_redacts_secrets_and_bounds_values():
    payload = {"api_key": "secret-value", "nested": {"password": "pw", "value": "ok"}}

    redacted = redact_trace_payload(payload)

    assert redacted["api_key"] == "[REDACTED]"
    assert redacted["nested"]["password"] == "[REDACTED]"
    assert redacted["nested"]["value"] == "ok"


def test_trace_payload_is_bounded():
    redacted = redact_trace_payload({"output": "x" * 10_000}, limit=100)

    assert redacted["truncated"] is True
    assert len(redacted["preview"]) == 100
