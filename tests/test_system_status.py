from audio_score_tool import system_status


def test_hf_auth_detects_environment_token(monkeypatch):
    monkeypatch.setenv("HF_TOKEN", "test-token")
    assert system_status.huggingface_authenticated() is True


def test_storage_status_has_capacity_fields(tmp_path, monkeypatch):
    monkeypatch.setenv("AST_DATA_DIR", str(tmp_path))
    status = system_status.storage_status()
    assert status["disk_total_bytes"] > 0
    assert status["disk_free_bytes"] >= 0
    assert status["jobs_bytes"] == 0
