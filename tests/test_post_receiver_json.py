from __future__ import annotations

import pytest

from trade_alerts.google_ledger_client import post_receiver_json


class _Response:
    def __init__(self, payload, status_code=200, headers=None):
        self._payload = payload
        self.status_code = status_code
        self.headers = headers or {}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("http error")

    def json(self):
        return self._payload


def test_returns_the_receivers_json_object_and_posts_without_following_redirects():
    seen = {}

    def post(url, **kwargs):
        seen.update(url=url, **kwargs)
        return _Response({"ok": True, "cell_chars": 12})

    assert post_receiver_json(endpoint="https://example.test/receiver", payload={"a": 1}, post=post) == {"ok": True, "cell_chars": 12}
    assert seen == {"url": "https://example.test/receiver", "json": {"a": 1}, "timeout": 15, "allow_redirects": False}


@pytest.mark.parametrize("endpoint", [None, "", "http://example.test/receiver", "ftp://example.test/x", 5])
def test_refuses_a_missing_or_non_https_endpoint_before_any_request(endpoint):
    def post(*args, **kwargs):
        raise AssertionError("must not be called")

    with pytest.raises(ValueError, match="endpoint_not_configured"):
        post_receiver_json(endpoint=endpoint, payload={}, post=post)


def test_apps_script_redirect_is_followed_to_its_content_host_only():
    calls = []
    answer = post_receiver_json(
        endpoint="https://script.google.com/macros/s/example/exec", payload={},
        post=lambda *a, **k: _Response({}, 302, {"Location": "https://script.googleusercontent.com/macros/echo"}),
        get=lambda location, **k: calls.append(location) or _Response({"ok": True}),
    )
    assert answer == {"ok": True} and calls == ["https://script.googleusercontent.com/macros/echo"]


@pytest.mark.parametrize("location", [
    "http://example.test/insecure", "https://evil.test/echo", "https://user:pw@example.test/x",
])
def test_a_redirect_to_another_host_or_scheme_or_with_credentials_is_refused(location):
    calls = []
    with pytest.raises(ValueError, match="receiver_redirect_not_allowed"):
        post_receiver_json(
            endpoint="https://example.test/receiver", payload={},
            post=lambda *a, **k: _Response({}, 302, {"Location": location}),
            get=lambda loc, **k: calls.append(loc) or _Response({"ok": True}),
        )
    assert calls == []


def test_script_google_com_does_not_whitelist_a_lookalike_host():
    with pytest.raises(ValueError, match="receiver_redirect_not_allowed"):
        post_receiver_json(
            endpoint="https://script.google.com/macros/s/example/exec", payload={},
            post=lambda *a, **k: _Response({}, 302, {"Location": "https://script.googleusercontent.com.evil.test/echo"}),
            get=lambda loc, **k: _Response({"ok": True}),
        )


def test_http_error_and_non_object_answers_raise():
    with pytest.raises(RuntimeError):
        post_receiver_json(endpoint="https://example.test/r", payload={}, post=lambda *a, **k: _Response({}, 500))
    for bad in ([], "text", None, 3):
        with pytest.raises(ValueError, match="receiver_invalid_response"):
            post_receiver_json(endpoint="https://example.test/r", payload={}, post=lambda *a, bad=bad, **k: _Response(bad))


def test_a_receiver_error_answer_is_returned_not_raised_so_the_caller_can_classify_it():
    answer = post_receiver_json(endpoint="https://example.test/r", payload={}, post=lambda *a, **k: _Response({"ok": False, "error": "request_not_fresh"}))
    assert answer == {"ok": False, "error": "request_not_fresh"}
