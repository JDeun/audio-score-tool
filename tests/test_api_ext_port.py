import pytest

from audio_score_tool import api_ext


def test_server_port_defaults_to_development_port(monkeypatch):
    monkeypatch.delenv("AST_API_PORT", raising=False)
    assert api_ext._server_port() == 8080


def test_server_port_accepts_packaged_runtime_port(monkeypatch):
    monkeypatch.setenv("AST_API_PORT", "49152")
    assert api_ext._server_port() == 49152


@pytest.mark.parametrize("value", ["", "abc", "0", "65536", "-1"])
def test_server_port_rejects_invalid_values(monkeypatch, value):
    monkeypatch.setenv("AST_API_PORT", value)
    with pytest.raises(RuntimeError, match="AST_API_PORT"):
        api_ext._server_port()
