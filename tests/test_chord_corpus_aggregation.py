"""Synthetic owned chord fixtures: per-song macro and fail-closed corpus gates."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

from scripts import aggregate_chord_corpus as corpus

SHA1 = "a" * 64
SHA2 = "b" * 64
SHA3 = "c" * 64


def _source(root: Path, name: str, payload: dict) -> str:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")
    return name


def _case(root: Path, *, id: str, sha: str, dataset: str = "casd",
          seconds: float = 4.0, incorrect: bool = False) -> dict:
    expected = "C:maj"
    observed = "D:maj" if incorrect else expected
    ref = {
        "schema_version": 1, "dataset": dataset,
        "license": "cc-by-nc-sa-4.0" if dataset == "casd" else "cc-by-4.0",
        "rights_reviewed_by_operator_only": True,
        "commercial_model_approved": False,
        "recording_sha256": sha, "duration_seconds": seconds,
        "annotators": [
            {"index": 0, "intervals": [{"start": 0.0, "end": seconds, "label": expected}]},
            {"index": 1, "intervals": [{"start": 0.0, "end": seconds, "label": expected}]},
        ],
    }
    model = {"schema_version": 1, "recording_sha256": sha,
             "duration_seconds": seconds,
             "chords": [{"time_seconds": 0.0, "label": observed}]}
    return {
        "id": id,
        "dataset_id": dataset,
        "split": "test",
        "recording_sha256": sha,
        "license": ref["license"],
        "rights_reviewed": True,
        "reference": _source(root, f"refs/{id}.json", ref),
        "manual": _source(root, f"manual/{id}.json", model),
        "sheetsage2": _source(root, f"sheetsage/{id}.json", model),
    }


def _setup(tmp_path: Path):
    root = tmp_path / "private-corpus"
    root.mkdir()
    manifest = {
        "schema_version": 1,
        "cases": [
            _case(root, id="song-one", sha=SHA1),
            _case(root, id="song-two", sha=SHA2, dataset="isophonics",
                  seconds=20.0, incorrect=True),
            _case(root, id="song-three", sha=SHA3),
        ],
    }
    registry = {"schema_version": 1, "datasets": [
        {"id": "casd", "task": "chord", "license": "cc-by-nc-sa-4.0",
         "status": "annotation_import_supported"},
        {"id": "isophonics", "task": "chord_beat", "license": "cc-by-4.0",
         "status": "verified_for_evaluation"},
    ]}
    return root, manifest, registry


def _fake_compare(reference, manual, sheetsage, *, inputs):
    """No-model, no-third-party fake to test aggregation independently."""
    correctness = float(reference["annotators"][0]["intervals"][0]["label"]
                        == manual["chords"][0]["label"])
    scored = {
        "chords": {"mean_by_metric": {
            key: correctness for key in ("root", "majmin", "thirds", "triads", "sevenths")
        }},
        "beat_f1": None, "downbeat_f1": None, "chord_boundary_f1_mean": None,
        "no_chord_recall_mean": None,
    }
    return {"duration_seconds": reference["duration_seconds"],
            "independent_annotators": len(reference["annotators"]),
            "by_model": {"manual": scored, "sheetsage2": scored},
            "inter_model_agreement_not_accuracy": {"root": 1.0}}


def test_song_macro_not_duration_or_annotator_micro_and_deterministic_bootstrap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
):
    root, manifest, registry = _setup(tmp_path)
    monkeypatch.setattr(corpus, "compare_chord_predictions", _fake_compare)
    report = corpus.evaluate_corpus(manifest, registry, corpus_root=root)
    macro = report["overall"]["by_candidate"]["manual"]["root"]
    assert macro["song_count"] == 3
    assert macro["macro_mean"] == pytest.approx(2 / 3)
    assert macro["song_bootstrap_ci95"][0] <= 2 / 3 <= macro["song_bootstrap_ci95"][1]
    assert report["by_dataset"]["casd"]["by_candidate"]["manual"]["root"]["macro_mean"] == 1
    assert report["by_dataset"]["isophonics"]["by_candidate"]["manual"]["root"]["macro_mean"] == 0
    assert report["overall"]["by_candidate"]["manual"]["beat_f1"]["song_count"] == 0
    assert report["overall"]["by_candidate"]["manual"]["beat_f1"]["macro_mean"] is None
    assert report["source_media_included"] is False
    assert report["commercial_model_approved"] is False
    assert report["model_inference_performed"] is False
    assert "/private-corpus/" not in json.dumps(report)
    reversed_manifest = {**manifest, "cases": list(reversed(manifest["cases"]))}
    again = corpus.evaluate_corpus(reversed_manifest, registry, corpus_root=root)
    assert report["overall"] == again["overall"]


@pytest.mark.parametrize(("tamper", "error"), [
    ("unreviewed", "rights review"),
    ("wrong-license", "license"),
    ("planned-dataset", "not registered"),
    ("wrong-task", "wrong evaluation task"),
    ("train-split", "validation/test"),
    ("duplicate-case", "duplicate"),
    ("duplicate-recording", "duplicate recording"),
    ("cross-split", "cross-split"),
    ("bad-reference-license", "reference license"),
    ("bad-reference-dataset", "reference dataset"),
    ("bad-reference-rights", "attestation"),
    ("bad-reference-fingerprint", "recording SHA-256"),
    ("bad-relative-path", "unsafe"),
])
def test_manifest_metadata_rejects_mismatches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, tamper: str, error: str,
):
    root, manifest, registry = _setup(tmp_path)
    monkeypatch.setattr(corpus, "compare_chord_predictions", _fake_compare)
    first, second = manifest["cases"][:2]
    reference_path = root / first["reference"]
    ref = json.loads(reference_path.read_text(encoding="utf-8"))
    if tamper == "unreviewed":
        first["rights_reviewed"] = False
    elif tamper == "wrong-license":
        first["license"] = "unverified"
    elif tamper == "planned-dataset":
        registry["datasets"][0]["status"] = "planned"
    elif tamper == "wrong-task":
        registry["datasets"][0]["task"] = "piano_amt"
    elif tamper == "train-split":
        first["split"] = "train"
    elif tamper == "duplicate-case":
        second["id"] = first["id"]
    elif tamper == "duplicate-recording":
        second["recording_sha256"] = first["recording_sha256"]
    elif tamper == "cross-split":
        second["recording_sha256"] = first["recording_sha256"]
        second["split"] = "validation"
    elif tamper == "bad-reference-license":
        ref["license"] = "cc-by-4.0"
    elif tamper == "bad-reference-dataset":
        ref["dataset"] = "unknown"
    elif tamper == "bad-reference-rights":
        ref["rights_reviewed_by_operator_only"] = False
    elif tamper == "bad-reference-fingerprint":
        ref["recording_sha256"] = "d" * 64
    elif tamper == "bad-relative-path":
        first["reference"] = "../escape.json"
    reference_path.write_text(json.dumps(ref), encoding="utf-8")
    with pytest.raises(ValueError, match=error):
        corpus.evaluate_corpus(manifest, registry, corpus_root=root)


def test_symlink_and_repository_output_protection(tmp_path: Path):
    root, manifest, registry = _setup(tmp_path)
    first = manifest["cases"][0]
    (root / first["manual"]).unlink()
    (root / first["manual"]).symlink_to(root / first["reference"])
    with pytest.raises(ValueError, match="symbolic"):
        corpus.evaluate_corpus(manifest, registry, corpus_root=root)


def test_independent_real_mir_eval_wcsr_if_available(tmp_path: Path):
    pytest.importorskip("mir_eval")
    root, manifest, registry = _setup(tmp_path)
    report = corpus.evaluate_corpus(manifest, registry, corpus_root=root)
    assert report["cases"][0]["metrics"]["manual"]["root"] == pytest.approx(1.0)
    assert report["cases"][1]["metrics"]["manual"]["root"] == pytest.approx(0.0)
    assert report["overall"]["by_candidate"]["manual"]["root"]["macro_mean"] == pytest.approx(
        2 / 3,
    )
    assert report["by_dataset"]["isophonics"]["song_count"] == 1


def test_cli_produces_private_json_csv_with_input_fingerprints(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture,
):
    root, manifest, registry = _setup(tmp_path)
    monkeypatch.setattr(corpus, "compare_chord_predictions", _fake_compare)
    manifest_file = tmp_path / "manifest.json"
    registry_file = tmp_path / "registry.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    registry_file.write_text(json.dumps(registry), encoding="utf-8")
    output = tmp_path / "report.json"
    table = tmp_path / "report.csv"
    monkeypatch.setattr(sys, "argv", [
        "aggregate_chord_corpus.py", str(manifest_file),
        "--registry", str(registry_file),
        "--corpus-root", str(root),
        "--output-json", str(output), "--output-csv", str(table),
    ])
    assert corpus.main() == 0
    assert json.loads(capsys.readouterr().out)["case_count"] == 3
    result = json.loads(output.read_text(encoding="utf-8"))
    assert len(result["manifest_sha256"]) == 64
    assert len(result["registry_sha256"]) == 64
    assert table.read_text(encoding="utf-8").count("song-one") == 2
    monkeypatch.setattr(sys, "argv", [
        "aggregate_chord_corpus.py", str(manifest_file),
        "--registry", str(registry_file),
        "--corpus-root", str(root), "--output-json", str(root / manifest["cases"][0]["manual"]),
    ])
    with pytest.raises(ValueError, match="overwrite source"):
        corpus.main()


def test_missing_optional_metric_is_not_zero(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    root, manifest, registry = _setup(tmp_path)
    monkeypatch.setattr(corpus, "compare_chord_predictions", _fake_compare)
    report = corpus.evaluate_corpus(manifest, registry, corpus_root=root)
    assert report["overall"]["by_candidate"]["manual"]["beat_f1"] == {
        "song_count": 0, "macro_mean": None, "song_bootstrap_ci95": None,
    }
