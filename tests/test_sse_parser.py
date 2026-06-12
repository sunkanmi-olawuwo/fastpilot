"""SSE parser unit tests (plan §6) — the risky frontend logic, fully headless."""

from __future__ import annotations

import api_client


def _lines(*blocks: str):
    """Flatten SSE text blocks into the line iterator requests.iter_lines yields."""
    out = []
    for block in blocks:
        out.extend(block.split("\n"))
    return out


def test_event_data_pairing():
    lines = _lines(
        'event: session\ndata: {"session_id": "sess_1"}\n',
        'event: token\ndata: {"token": "hello"}\n',
    )
    events = list(api_client.parse_sse_lines(lines))
    assert events[0] == ("session", {"session_id": "sess_1"})
    assert events[1] == ("token", {"token": "hello"})


def test_blank_line_is_dispatch_boundary():
    lines = ["event: a", 'data: {"x": 1}', "", "event: b", 'data: {"y": 2}', ""]
    events = list(api_client.parse_sse_lines(lines))
    assert events == [("a", {"x": 1}), ("b", {"y": 2})]


def test_malformed_data_skipped_not_raised():
    lines = ["event: token", "data: {not valid json", "event: token", 'data: {"token": "ok"}']
    events = list(api_client.parse_sse_lines(lines))
    assert events == [("token", {"token": "ok"})]


def test_comment_and_heartbeat_ignored():
    lines = [": keep-alive", 'data: {"token": "x"}']
    events = list(api_client.parse_sse_lines(lines))
    assert events == [("message", {"token": "x"})]  # no event: → defaults to "message"


def test_error_event_surfaced():
    events = list(api_client.parse_sse_lines(_lines('event: error\ndata: {"error": "boom"}')))
    assert events == [("error", {"error": "boom"})]


def test_bytes_lines_decoded():
    lines = [b"event: token", b'data: {"token": "b"}']
    events = list(api_client.parse_sse_lines(lines))
    assert events == [("token", {"token": "b"})]


def test_full_stream_order():
    raw = (
        'event: session\ndata: {"session_id": "s"}\n\n'
        'event: cache_status\ndata: {"cache_hit": false}\n\n'
        'event: classification\ndata: {"category": "HOW_TO"}\n\n'
        'event: context\ndata: {"rank": 1, "content": "c"}\n\n'
        'event: token\ndata: {"token": "A"}\n\n'
        'event: done\ndata: {"msg_id": "msg_1"}\n\n'
    )
    names = [e for e, _ in api_client.parse_sse_lines(raw.split("\n"))]
    assert names == ["session", "cache_status", "classification", "context", "token", "done"]


# --- pure style helpers ---------------------------------------------------
def test_render_answer_wraps_citations_not_indexing():
    import styles

    out = styles.render_answer("Use OAuth2 [1] but not items[0].")
    assert '<sup class="fp-cite">[1]</sup>' in out
    assert "items[0]" in out  # list indexing left alone


def test_badges_html_combinations():
    import styles

    assert styles.badges_html() == ""
    html = styles.badges_html(rewritten=True, cache_hit=True, query_type="HOW_TO")
    assert "rewritten" in html and "cache hit" in html and "HOW-TO" in html
