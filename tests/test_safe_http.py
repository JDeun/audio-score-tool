import urllib.error
import urllib.request

import pytest

from audio_score_tool.safe_http import SafeRedirectHandler


def test_sensitive_post_cross_origin_redirect_is_blocked():
    handler = SafeRedirectHandler()
    request = urllib.request.Request(
        "https://api.example.test/v1/chat/completions",
        data=b"{}",
        headers={"Authorization": "Bearer secret"},
        method="POST",
    )

    with pytest.raises(urllib.error.HTTPError) as caught:
        handler.redirect_request(
            request,
            None,
            307,
            "Temporary Redirect",
            {},
            "https://evil.example.test/collect",
        )
    assert caught.value.code == 403


def test_same_origin_sensitive_redirect_remains_allowed():
    handler = SafeRedirectHandler()
    request = urllib.request.Request(
        "https://api.example.test/v1/chat/completions",
        data=b"{}",
        headers={"Authorization": "Bearer secret"},
        method="POST",
    )

    redirected = handler.redirect_request(
        request,
        None,
        307,
        "Temporary Redirect",
        {},
        "https://api.example.test/v1/chat/completions/",
    )
    assert redirected is not None
    assert redirected.full_url == "https://api.example.test/v1/chat/completions/"
