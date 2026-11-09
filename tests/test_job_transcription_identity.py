"""Exercise actual admission, SQLite, workers and retry around settings changes.

Inference and YouTube download are substitutes: these tests validate the model
sent to those boundaries, not model quality or live service availability.
"""
from __future__ import annotations

import hashlib
from dataclasses import replace
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from audio_score_tool import api
from audio_score_tool import job_lifecycle_api_v2 as lifecycle
from audio_score_tool import job_transcription_settings as binding
from audio_score_tool import runtime_services as runtime
from audio_score_tool import runtime_settings as settings_module
from audio_score_tool import upload_api_v2 as upload
from audio_score_tool.config import Settings
from audio_score_tool.job_store import JobStore


@pytest.fixture
def flow(tmp_path, monkeypatch):
    monkeypatch.delenv("AST_PACKAGED", raising=False)
    store = JobStore(tmp_path / "jobs.sqlite3")
    state = SimpleNamespace(
        store=store, root=tmp_path / "jobs", threads=[], inferred=[], downloads=[],
        checked=[], available=True,
        settings=Settings(
            usage_mode="personal", transcription_engine="mt3_infer", mt3_model="mr_mt3",
            muscriptor_model="small", whisperx_model="small",
        ),
    )
    monkeypatch.setattr(api, "_store", store)
    monkeypatch.setattr(runtime, "_store", store)
    monkeypatch.setattr(api, "_reconcile_completed_job_batch", lambda: None)
    for module in (upload, lifecycle, runtime):
        monkeypatch.setattr(module, "jobs_dir", lambda: state.root)

    def ready(settings, **_kwargs):
        state.checked.append(settings)
        return {"ok": state.available, "missing": [] if state.available else ["selected-model"]}

    for module in (upload, lifecycle, runtime):
        monkeypatch.setattr(module, "preflight", ready)
    for module in (upload, lifecycle):
        monkeypatch.setattr(module, "runtime_settings", lambda: replace(state.settings))
    monkeypatch.setattr(runtime, "_runtime_settings", lambda **kw: replace(state.settings, **kw))
    monkeypatch.setattr(lifecycle, "youtube_tool_status", lambda _settings: {"ready": True})

    class DeferredThread:
        def __init__(self, *, target, args, daemon):
            self.target, self.args = target, args
            state.threads.append(self)

        def start(self):
            pass

        def finish(self):
            self.target(*self.args)

    for module in (upload, lifecycle):
        monkeypatch.setattr(module, "Thread", DeferredThread)

    def infer(_audio, _output, *, settings, **_kwargs):
        state.inferred.append(settings)
        return SimpleNamespace(warnings=[], as_dict=lambda: {"warnings": []})

    def download(_url, output, *, settings, **_kwargs):
        state.downloads.append(settings)
        output.mkdir(parents=True, exist_ok=True)
        audio = output / "input.wav"
        audio.write_bytes(b"synthetic download boundary")
        return audio, SimpleNamespace(title="Original recording")

    monkeypatch.setattr(runtime, "transcribe", infer)
    monkeypatch.setattr(runtime, "download_youtube_audio", download)
    state.client = TestClient(api.app)
    return state


def submit(flow, source, **values):
    payload = {"skip_lyrics": True, "auto_enrich": False, **values}
    if source == "youtube":
        return flow.client.post(
            "/api/jobs/youtube",
            json={"url": "https://www.youtube.com/watch?v=abcdef12345", **payload},
        )
    return flow.client.post(
        "/api/jobs", files={"file": ("original.wav", b"synthetic input", "audio/wav")},
        data=payload,
    )


@pytest.mark.parametrize("source", ["file", "youtube"])
def test_admitted_engine_and_mt3_model_survive_queue_settings_changes_and_retry(flow, source):
    reply = submit(flow, source)
    assert reply.status_code == 202, reply.text
    job_id = reply.json()["job_id"]
    first = flow.store.get(job_id)
    assert (first["transcription_engine"], first["mt3_model"]) == ("mt3_infer", "mr_mt3")

    # A different MT3 selection is saved while this job waits for inference.
    flow.settings = replace(flow.settings, mt3_model="yourmt3")
    flow.threads[-1].finish()
    assert flow.store.get(job_id)["status"] == "done"
    assert flow.inferred[-1].mt3_model == "mr_mt3"
    if source == "youtube":
        assert flow.downloads[-1].mt3_model == "mr_mt3"

    # Retry keeps the previous job's engine even after changing providers.
    flow.settings = replace(flow.settings, transcription_engine="muscriptor", muscriptor_model="large")
    retried = flow.client.post(f"/api/jobs/{job_id}/retry")
    assert retried.status_code == 202, retried.text
    new_id = retried.json()["job_id"]
    new = flow.store.get(new_id)
    assert (new["transcription_engine"], new["mt3_model"]) == ("mt3_infer", "mr_mt3")
    assert flow.checked[-1].transcription_engine == "mt3_infer"
    assert flow.checked[-1].mt3_model == "mr_mt3"
    flow.threads[-1].finish()
    assert flow.store.get(new_id)["status"] == "done"
    assert [(s.transcription_engine, s.mt3_model) for s in flow.inferred] == [
        ("mt3_infer", "mr_mt3"), ("mt3_infer", "mr_mt3"),
    ]
    public = flow.client.get(f"/api/jobs/{new_id}").json()
    assert public["mt3_model"] == "mr_mt3"
    assert not any(key.endswith("_cmd") or "token" in key for key in public)


@pytest.mark.parametrize("source", ["file", "youtube"])
@pytest.mark.parametrize(("preset", "requested", "expected"), [
    ("quality", None, "large"), ("balanced", "small", "small"),
])
def test_preflight_checks_effective_preset_and_override_before_accepting_input(
    flow, monkeypatch, source, preset, requested, expected,
):
    flow.settings = replace(flow.settings, transcription_engine="muscriptor")
    seen = []

    def only_small_ready(settings, **_kwargs):
        seen.append(settings.muscriptor_model)
        return {"ok": settings.muscriptor_model == "small", "missing": ["muscriptor-large"]}

    for module in (upload, lifecycle):
        monkeypatch.setattr(module, "preflight", only_small_ready)
    fields = {"preset": preset}
    if requested:
        fields["muscriptor_model"] = requested
    response = submit(flow, source, **fields)
    assert seen == [expected]
    assert flow.settings.muscriptor_model == "small"
    if expected == "large":
        assert response.status_code == 503
        assert flow.store.list() == []
        assert flow.threads == []
        assert not flow.root.exists()
    else:
        assert response.status_code == 202, response.text
        assert flow.store.get(response.json()["job_id"])["muscriptor_model"] == "small"


def test_queued_muscriptor_is_rejected_after_commercial_mode_change_without_fallback(flow):
    flow.settings = replace(flow.settings, transcription_engine="muscriptor")
    job_id = submit(flow, "file").json()["job_id"]
    flow.settings = replace(flow.settings, usage_mode="commercial", transcription_engine="mt3_infer")
    flow.threads[-1].finish()
    row = flow.store.get(job_id)
    assert row["status"] == "failed"
    assert "commercial" in row["error"]
    assert row["transcription_engine"] == "muscriptor"
    assert flow.inferred == []
    retry = flow.client.post(f"/api/jobs/{job_id}/retry")
    assert retry.status_code == 409
    assert len(flow.store.list()) == 1
    assert not runtime._inference_lock.locked()


def test_queued_yourmt3_is_not_replaced_by_packaged_mr_only_model(flow, monkeypatch):
    flow.settings = replace(flow.settings, mt3_model="yourmt3")
    job_id = submit(flow, "file").json()["job_id"]
    flow.settings = replace(flow.settings, mt3_model="mr_mt3")
    monkeypatch.setattr(binding, "packaged_runtime", lambda: True)
    monkeypatch.setattr(settings_module, "published_managed_mt3_model", lambda: "mr_mt3")
    flow.threads[-1].finish()
    row = flow.store.get(job_id)
    assert row["status"] == "failed"
    assert "supports mr_mt3" in row["error"]
    assert row["mt3_model"] == "yourmt3"
    assert flow.inferred == []
    assert flow.client.post(f"/api/jobs/{job_id}/retry").status_code == 409
    assert len(flow.store.list()) == 1


def test_model_removed_after_admission_fails_execution_and_retry_before_copy(flow):
    job_id = submit(flow, "file").json()["job_id"]
    flow.available = False
    flow.threads[-1].finish()
    assert flow.store.get(job_id)["status"] == "failed"
    assert "selected-model" in flow.store.get(job_id)["error"]
    assert flow.inferred == []
    assert flow.client.post(f"/api/jobs/{job_id}/retry").status_code == 503
    assert [path.name for path in flow.root.iterdir()] == [job_id]
    assert len(flow.store.list()) == 1


@pytest.mark.parametrize(("column", "message"), [
    ("mt3_model", "MT3 model is missing"), ("whisperx_model", "WhisperX model is missing"),
])
def test_incomplete_new_model_identity_does_not_fall_back_to_current_settings(flow, column, message):
    job_id = submit(flow, "file").json()["job_id"]
    with flow.store._connect() as connection:
        connection.execute(f"UPDATE jobs SET {column}=NULL WHERE job_id=?", (job_id,))
    flow.threads[-1].finish()
    assert flow.store.get(job_id)["status"] == "failed"
    assert message in flow.store.get(job_id)["error"]
    assert flow.inferred == []
    assert flow.client.post(f"/api/jobs/{job_id}/retry").status_code == 409
    assert len(flow.store.list()) == 1


def test_legacy_retry_records_current_engine_without_inventing_historical_identity(flow):
    original = flow.root / "old" / "input.wav"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"historical private input")
    flow.store.create("old", status="failed", muscriptor_model="medium", whisperx_model="small")
    response = flow.client.post("/api/jobs/old/retry")
    assert response.status_code == 202, response.text
    old, new = flow.store.get("old"), flow.store.get(response.json()["job_id"])
    assert old["transcription_engine"] is None and old["mt3_model"] is None
    assert old["transcription_selection_version"] == 0
    assert new["transcription_selection_version"] == 1
    assert new["transcription_engine"] == "mt3_infer" and new["mt3_model"] == "mr_mt3"
    flow.threads[-1].finish()
    assert flow.inferred[-1].mt3_model == "mr_mt3"


def test_lost_new_engine_identity_is_not_treated_as_a_legacy_job(flow):
    job_id = submit(flow, "file").json()["job_id"]
    with flow.store._connect() as connection:
        connection.execute(
            "UPDATE jobs SET transcription_engine=NULL, mt3_model=NULL WHERE job_id=?", (job_id,),
        )
    flow.threads[-1].finish()
    row = flow.store.get(job_id)
    assert row["status"] == "failed"
    assert "engine is missing" in row["error"]
    assert flow.inferred == []
    assert flow.client.post(f"/api/jobs/{job_id}/retry").status_code == 409


def test_legacy_worker_binds_its_actual_attempt_once(flow):
    flow.store.create("old-queued", muscriptor_model="small", whisperx_model="small")
    runtime._worker("old-queued", flow.root / "input.wav", None, True, "small", "small")
    row = flow.store.get("old-queued")
    assert row["status"] == "done"
    assert (row["transcription_engine"], row["mt3_model"]) == ("mt3_infer", "mr_mt3")


def test_native_choice_hashes_only_active_model_and_rejects_changed_weights(flow, tmp_path):
    weights = tmp_path / "native.pt"
    weights.write_bytes(b"original test model bytes")
    flow.settings = replace(flow.settings, transcription_engine="native", native_checkpoint=weights)
    job_id = submit(flow, "file").json()["job_id"]
    row = flow.store.get(job_id)
    assert row["native_checkpoint_sha256"] == hashlib.sha256(weights.read_bytes()).hexdigest()
    assert row["mt3_model"] is None
    assert "native_checkpoint" not in row
    weights.write_bytes(b"different model bytes")
    flow.threads[-1].finish()
    assert flow.store.get(job_id)["status"] == "failed"
    assert "checkpoint has changed" in flow.store.get(job_id)["error"]
    assert flow.inferred == []
    assert flow.client.post(f"/api/jobs/{job_id}/retry").status_code == 409


def test_native_runtime_path_may_move_when_checkpoint_content_is_unchanged(flow, tmp_path):
    weights = tmp_path / "before.pt"
    weights.write_bytes(b"same Native model")
    flow.settings = replace(flow.settings, transcription_engine="native", native_checkpoint=weights)
    job_id = submit(flow, "file").json()["job_id"]
    moved = tmp_path / "after.pt"
    weights.rename(moved)
    flow.settings = replace(flow.settings, native_checkpoint=moved)
    flow.threads[-1].finish()
    assert flow.store.get(job_id)["status"] == "done"
    assert flow.inferred[-1].native_checkpoint == moved


def test_inactive_native_model_is_not_read(flow, monkeypatch):
    def forbidden(_settings):
        raise AssertionError("MT3 must not inspect an unrelated Native checkpoint")
    monkeypatch.setattr(binding, "_native_checkpoint_sha256", forbidden)
    response = submit(flow, "file")
    assert response.status_code == 202
    flow.threads[-1].finish()
    assert flow.store.get(response.json()["job_id"])["status"] == "done"
