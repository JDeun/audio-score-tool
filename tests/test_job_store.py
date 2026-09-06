from pathlib import Path

from audio_score_tool.job_store import JobStore


def test_job_store_round_trip(tmp_path: Path):
    store = JobStore(tmp_path / "jobs.sqlite3")
    store.create(
        "abc",
        filename="song.wav",
        language="ko",
        preset="balanced",
        muscriptor_model="medium",
        whisperx_model="small",
    )
    store.update("abc", status="done", progress=100, result={"midi": "/tmp/a.mid"})

    job = store.get("abc")
    assert job is not None
    assert job["status"] == "done"
    assert job["result"]["midi"] == "/tmp/a.mid"
    assert store.list()[0]["job_id"] == "abc"
    assert store.delete("abc") is True
    assert store.get("abc") is None


def test_stale_running_jobs_are_marked_interrupted(tmp_path: Path):
    path = tmp_path / "jobs.sqlite3"
    store = JobStore(path)
    store.create("run", status="running")
    restarted = JobStore(path)
    assert restarted.get("run")["status"] == "interrupted"
