"""CPU-only specialist diagnostics; not a product-quality or held-out approval.

Real pretrained inference, small predeclared cases, private temporary media,
metadata-only reports. Piano inputs are original synthetic SoundFont renders.
GuitarSet string accuracy is CONDITIONAL on reference onset/pitch, not AMT.
Beat This final0 saw GuitarSet in training; its scores are seen-data diagnostics.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import math
import os
import platform
import random
import subprocess
import sys
import time
import urllib.parse
import urllib.request
import zipfile
from importlib.metadata import distributions
from pathlib import Path
from statistics import mean

import numpy as np

SONG_REV = "6aee2a2139b28af871f4c9a878b7e18650c38226"
RESCORED_REV = "4c7dd9dfebc96560073cfd06b114d6ca35938ba2"
BEAT_REV = "b95c8ab0c58c2d9fcfd40508ae8dffbc05ac4f5c"
PIANO_REV = "0226e74cbc805660e34bbd6a8fed2083890ebb88"
GUITAR_MD5 = {
    "annotation.zip": "b39b78e63d3446f2e54ddb7a54df9b10",
    "audio_mono-mic.zip": "275966d6610ac34999b58426beb119c3",
}
BEAT_SHA = "8c328b45f59d8dd3dff219253ff6a8d6482be57d0133a29140e2febbf8eb8331"
ALLOWED_HOSTS = {"raw.githubusercontent.com", "zenodo.org", "cloud.cp.jku.at"}
TUNING = np.array([40, 45, 50, 55, 59, 64])
REPORT_OUTPUT: Path | None = None


def checkpoint_report(report: dict) -> None:
    if REPORT_OUTPUT is not None:
        REPORT_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
        REPORT_OUTPUT.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")


def file_hash(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def verify_blob(path: Path, expected: str, size: int) -> None:
    if path.is_symlink() or path.stat().st_size != size:
        raise ValueError("Pinned blob size/type mismatch")
    digest = hashlib.sha1(f"blob {size}\0".encode())
    with path.open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    if digest.hexdigest() != expected:
        raise ValueError("Pinned Git blob mismatch")


class HTTPSOnly(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def check_url(url: str) -> None:
    parsed = urllib.parse.urlsplit(url)
    if parsed.scheme != "https" or parsed.hostname not in ALLOWED_HOSTS:
        raise ValueError("Download host is not allowlisted HTTPS")
    if parsed.username or parsed.password or parsed.port not in (None, 443):
        raise ValueError("Unexpected download credentials/port")


def download(url: str, path: Path, *, limit: int, digest: str | None = None,
             algorithm: str = "sha256") -> dict:
    check_url(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() or path.is_symlink():
        raise ValueError("Refusing to overwrite a download")
    part = path.with_suffix(path.suffix + ".part")
    opener = urllib.request.build_opener(HTTPSOnly())
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "AudioScoreTool-research/1"})
            with opener.open(req, timeout=90) as response, part.open("xb") as out:
                total = 0
                for chunk in iter(lambda: response.read(1024 * 1024), b""):
                    total += len(chunk)
                    if total > limit:
                        raise ValueError("Download exceeded byte budget")
                    out.write(chunk)
            if not total or (digest and file_hash(part, algorithm) != digest):
                raise ValueError("Downloaded checksum/empty payload mismatch")
            part.replace(path)
            return {"url": url, "bytes": total, "sha256": file_hash(path),
                    "expected_digest": digest, "digest_algorithm": algorithm}
        except (OSError, TimeoutError):
            if attempt == 2:
                raise
            time.sleep(2 ** attempt)
        finally:
            part.unlink(missing_ok=True)
    raise RuntimeError("Unreachable download state")


def pinned_source(work: Path, repo: str, revision: str, relative: str,
                  blob: str, size: int, dest: Path | None = None) -> tuple[Path, dict]:
    path = dest or work / relative
    proof = download(f"https://raw.githubusercontent.com/{repo}/{revision}/{relative}",
                     path, limit=size)
    verify_blob(path, blob, size)
    return path, {**proof, "source_revision": revision, "git_blob_verified": blob}


def selected_jams(names: list[str]) -> list[str]:
    result = []
    for player in ("03", "04", "05"):
        for mode in ("comp", "solo"):
            matches = sorted(n for n in names if Path(n).name.startswith(player + "_")
                             and Path(n).name.endswith("_" + mode + ".jams")
                             and "__MACOSX" not in Path(n).parts)
            if not matches:
                raise ValueError(f"Missing predeclared GuitarSet group {player}/{mode}")
            result.append(matches[0])
    if len(set(result)) != 6:
        raise ValueError("Ambiguous selected recordings")
    return result


def zip_bytes(archive: zipfile.ZipFile, name: str, limit: int) -> bytes:
    info = archive.getinfo(name)
    if info.is_dir() or info.file_size > limit or info.file_size <= 0:
        raise ValueError("Unsafe or empty archive member")
    return archive.read(info)


def guitar_cases(work: Path, report: dict) -> list[tuple[Path, dict, dict]]:
    paths = {}
    report["dataset"] = "GuitarSet-1.1.0-six-predeclared-performer-mode-examples"
    report["dataset_license"] = "CC-BY-4.0"
    report["dataset_sources"] = []
    for name, digest in GUITAR_MD5.items():
        paths[name] = work / name
        proof = download(f"https://zenodo.org/records/3371780/files/{name}?download=1",
                         paths[name], limit=750_000_000, digest=digest, algorithm="md5")
        report["dataset_sources"].append(proof)
    cases = []
    with zipfile.ZipFile(paths["annotation.zip"]) as annotations, \
            zipfile.ZipFile(paths["audio_mono-mic.zip"]) as recordings:
        for name in selected_jams(annotations.namelist()):
            raw = zip_bytes(annotations, name, 10_000_000)
            case_id = Path(name).stem
            matching = [n for n in recordings.namelist()
                        if Path(n).name == case_id + "_mic.wav" and "__MACOSX" not in Path(n).parts]
            if len(matching) != 1:
                raise ValueError("Missing or ambiguous audio pair")
            audio = work / (case_id + ".wav")
            audio.write_bytes(zip_bytes(recordings, matching[0], 100_000_000))
            cases.append((audio, json.loads(raw), {
                "id": case_id, "audio_sha256": file_hash(audio),
                "annotation_sha256": hashlib.sha256(raw).hexdigest(),
            }))
    report["planned_case_ids"] = [item[2]["id"] for item in cases]
    return cases


def guitar_notes(jams: dict) -> tuple[list[tuple[float, int]], np.ndarray]:
    indexed = {}
    for ann in jams["annotations"]:
        if ann["namespace"] != "note_midi":
            continue
        index = int(ann["annotation_metadata"]["data_source"])
        if index not in range(6) or index in indexed:
            raise ValueError("Ambiguous GuitarSet string annotation")
        indexed[index] = ann["data"]
    if set(indexed) != set(range(6)):
        raise ValueError("Expected all six string annotations")
    rows = []
    for string, data in indexed.items():
        for note in data:
            onset, pitch, duration = float(note["time"]), float(note["value"]), float(note["duration"])
            if not all(math.isfinite(v) for v in (onset, pitch, duration)) or onset < 0 or duration <= 0:
                raise ValueError("Invalid note annotation")
            midi_pitch = round(pitch)  # This model requires a discrete supplied pitch.
            if not 0 <= midi_pitch - TUNING[string] <= 20:
                raise ValueError("String/pitch mapping outside the model's 20-fret support")
            rows.append((onset, midi_pitch, string))
    rows.sort()
    if not rows:
        raise ValueError("No reference notes")
    return [(t, p) for t, p, _ in rows], np.asarray([s for _, _, s in rows])


def beat_references(jams: dict) -> tuple[np.ndarray, np.ndarray]:
    annotations = [a for a in jams["annotations"] if a["namespace"] == "beat_position"]
    if len(annotations) != 1:
        raise ValueError("Ambiguous beat annotation")
    data = annotations[0]["data"]
    beats = np.asarray([float(n["time"]) for n in data])
    downbeats = np.asarray([float(n["time"]) for n in data if int(n["value"]["position"]) == 1])
    for times in (beats, downbeats):
        if len(times) < 2 or not np.all(np.isfinite(times)) or np.any(np.diff(times) <= 0):
            raise ValueError("Invalid reference beat times")
    return beats, downbeats


def run_strings(work: Path, report: dict) -> None:
    import librosa

    proofs = []
    modules = [
        ("song2sheet/__init__.py", "f79ae9ce3fe46283cd06a57bba34dc090ead4dda", 64),
        ("song2sheet/fret.py", "31d4e22a035b373983c932a150f3ec00fbd10fa6", 6328),
        ("song2sheet/stringnet.py", "c43a06bf39ddcfcd753224ef2275388ceb4669cc", 3916),
        ("song2sheet/weights/stringnet.pt", "26a7ee8dce9b13c523a390f754a9f50d34067e00", 1497761),
        ("LICENSE", "153f8c8d5c35dd1885980419094765e8140e251c", 1073),
    ]
    for relative, blob, size in modules:
        _, proof = pinned_source(work, "kishormorol/song2sheet", SONG_REV, relative, blob, size)
        proofs.append(proof)
    report.update(model_sources=proofs, task="conditional-string-classification",
                  reference_onset_pitch_provided=True, end_to_end_amt_evaluated=False,
                  pitch_preprocessing="round reference MIDI pitch for StringNet input only",
                  training_overlap="author claims training players 00-02; selected 03-05; not independently audited")
    sys.path.insert(0, str(work))
    from song2sheet import fret, stringnet

    if list(fret.TUNING) != list(TUNING) or fret.MAX_FRET != 20:
        raise ValueError("Pinned model tuning contract mismatch")
    model = stringnet.load("cpu")
    for audio, jams, row in guitar_cases(work, report):
        inputs, labels = guitar_notes(jams)
        y, sr = librosa.load(audio, sr=stringnet.SR, mono=True)
        started = time.perf_counter()
        probabilities = stringnet.string_log_probs(model, y, inputs, device="cpu")
        if probabilities.shape != (len(labels), 6) or not np.all(np.isfinite(probabilities)):
            raise ValueError("Invalid StringNet output")
        pitches = np.asarray([p for _, p in inputs])
        frets = pitches[:, None] - TUNING[None, :]
        lowest = np.argmin(np.where((frets >= 0) & (frets <= 20), frets, 999), axis=1)
        row.update(status="scored", reference_notes=len(labels),
                   correct=int(np.sum(probabilities.argmax(1) == labels)),
                   lowest_fret_correct=int(np.sum(lowest == labels)),
                   string_accuracy=float(np.mean(probabilities.argmax(1) == labels)),
                   lowest_fret_accuracy=float(np.mean(lowest == labels)),
                   inference_seconds=time.perf_counter() - started, sample_rate=sr)
        report["cases"].append(row)
        checkpoint_report(report)
        print("StringNet scored", row["id"], flush=True)
    report["macro"] = {k: mean(r[k] for r in report["cases"])
                       for k in ("string_accuracy", "lowest_fret_accuracy")}


def run_beats(work: Path, report: dict) -> None:
    import mir_eval
    import soundfile as sf
    from beat_this.inference import Audio2Beats

    checkpoint = work / "final0.ckpt"
    proof = download("https://cloud.cp.jku.at/public.php/dav/files/7ik4RrBKTS273gp/final0.ckpt",
                     checkpoint, limit=100_000_000, digest=BEAT_SHA)
    report.update(model_sources=[proof], source_revision=BEAT_REV,
                  checkpoint_pin_source="https://huggingface.co/musetric/beat-this-onnx#source--lineage",
                  task="beat-and-downbeat", training_overlap="GuitarSet included in final0 training",
                  evaluation_scope="seen-training-dataset diagnostic, NOT held-out generalization",
                  dbn=False, beat_tolerance_seconds=0.07, evaluation_trim_seconds=5.0)
    model = Audio2Beats(checkpoint_path=str(checkpoint), device="cpu", dbn=False)
    for audio, jams, row in guitar_cases(work, report):
        y, sr = sf.read(audio, dtype="float32")
        expected = beat_references(jams)
        started = time.perf_counter()
        actual = model(y, sr)
        if len(actual) != 2:
            raise ValueError("Expected beat and downbeat outputs")
        row.update(status="scored", inference_seconds=time.perf_counter() - started)
        for name, truth, estimates in zip(("beat", "downbeat"), expected, actual):
            estimates = np.asarray(estimates)
            if estimates.ndim != 1 or not np.all(np.isfinite(estimates)):
                raise ValueError("Invalid beat prediction")
            if len(estimates) and (np.any(estimates < 0) or np.any(np.diff(estimates) <= 0)):
                raise ValueError("Non-monotonic beat prediction")
            truth = mir_eval.beat.trim_beats(truth, min_beat_time=5.0)
            estimates = mir_eval.beat.trim_beats(estimates, min_beat_time=5.0)
            if not len(truth):
                raise ValueError("No reference events after declared trim")
            row[name + "_f1"] = float(mir_eval.beat.f_measure(truth, estimates, f_measure_threshold=0.07)) if len(estimates) else 0.0
            row[name + "_reference_count"] = len(truth)
            row[name + "_prediction_count"] = len(estimates)
        report["cases"].append(row)
        checkpoint_report(report)
        print("Beat This scored", row["id"], flush=True)
    report["macro"] = {k: mean(r[k] for r in report["cases"]) for k in ("beat_f1", "downbeat_f1")}


def score_midi(reference: Path, prediction: Path) -> dict:
    import mir_eval
    import pretty_midi

    def events(path):
        notes = [n for part in pretty_midi.PrettyMIDI(str(path)).instruments
                 if not part.is_drum for n in part.notes]
        notes.sort(key=lambda n: (n.start, n.pitch, n.end))
        intervals = np.asarray([(n.start, n.end) for n in notes], dtype=float).reshape(-1, 2)
        hz = np.asarray([440.0 * 2 ** ((n.pitch - 69) / 12) for n in notes])
        if not np.all(np.isfinite(intervals)) or np.any(intervals[:, 1] <= intervals[:, 0]):
            raise ValueError("Invalid MIDI note events")
        return intervals, hz

    ref, ref_hz = events(reference)
    pred, pred_hz = events(prediction)
    if not len(ref):
        raise ValueError("Empty synthetic truth")
    scores = {"reference_notes": len(ref), "predicted_notes": len(pred),
              "prediction_sha256": file_hash(prediction)}
    for name, ratio in (("onset", None), ("onset_offset", 0.2)):
        p, r, f, _ = mir_eval.transcription.precision_recall_f1_overlap(
            ref, ref_hz, pred, pred_hz, onset_tolerance=0.05, pitch_tolerance=50,
            offset_ratio=ratio, offset_min_tolerance=0.05,
        ) if len(pred) else (0.0, 0.0, 0.0, 0.0)
        scores[name] = {"precision": float(p), "recall": float(r), "f1": float(f)}
    return scores


def piano_fixtures(work: Path) -> list[tuple[Path, Path]]:
    import pretty_midi

    specs = [
        ("melody", [(0.5 + i * 0.5, 0.35, p) for i, p in enumerate([60, 62, 64, 67, 65, 64, 62, 60] * 2)]),
        ("chords", [(0.5 + i * 0.9, 0.65, p) for i in range(10) for p in (48+i%4, 60+i%4, 64+i%4, 67+i%4)]),
        ("octave-repeats", [(0.5 + i * 0.4, 0.25, [48, 60, 72, 60][i % 4]) for i in range(24)]),
    ]
    soundfont = Path("/usr/share/sounds/sf2/TimGM6mb.sf2")
    if not soundfont.is_file():
        raise RuntimeError("Declared TimGM6mb soundfont unavailable")
    cases = []
    for name, events in specs:
        midi, audio = work / (name + ".mid"), work / (name + ".wav")
        pm = pretty_midi.PrettyMIDI(initial_tempo=120, resolution=960)
        piano = pretty_midi.Instrument(program=0)
        piano.notes = [pretty_midi.Note(velocity=80, pitch=p, start=t, end=t+d) for t, d, p in events]
        pm.instruments.append(piano)
        pm.write(str(midi))
        subprocess.run(["fluidsynth", "-ni", "-R", "0", "-C", "0", "-g", "0.5", "-r", "16000",
                        "-T", "wav", "-F", str(audio), str(soundfont), str(midi)],
                       check=True, timeout=90, stdout=subprocess.DEVNULL)
        cases.append((audio, midi))
    return cases


def run_piano(work: Path, report: dict) -> None:
    import basic_pitch
    import librosa
    import onnxruntime as ort
    from basic_pitch.inference import Model, predict
    from piano_transcription_inference import PianoTranscription

    report.update(task="synthetic-piano-amt-and-midi-postprocessing",
                  dataset="three-original-TimGM6mb-renders", real_music_quality_evaluated=False,
                  reference_notes_provided_to_model=False, pitch_bends_scored=False,
                  reference_policy="original generated MIDI note-off; no sustain pedal",
                  soundfont_sha256=file_hash(Path("/usr/share/sounds/sf2/TimGM6mb.sf2")))
    meta_path = work / "piano-source-record.json"
    download("https://zenodo.org/api/records/4034264", meta_path, limit=2_000_000)
    meta = json.loads(meta_path.read_text())
    name = "CRNN_note_F1=0.9677_pedal_F1=0.9186.pth"
    match = [f for f in meta["files"] if f["key"] == name]
    if len(match) != 1 or not match[0]["checksum"].startswith("md5:"):
        raise ValueError("Missing authoritative piano model checksum")
    checkpoint = work / "piano.pth"
    proof = download(f"https://zenodo.org/records/4034264/files/{urllib.parse.quote(name)}?download=1",
                     checkpoint, limit=200_000_000,
                     digest=match[0]["checksum"].split(":", 1)[1], algorithm="md5")
    if checkpoint.stat().st_size != match[0]["size"] or checkpoint.stat().st_size < 160_000_000:
        raise ValueError("Piano model size drift")
    asset = Path(basic_pitch.__file__).parent / "saved_models/icassp_2022/nmp.onnx"
    verify_blob(asset, "c30e5f9438e798604b7177aa26be1fe64482f767", 230444)
    report["model_sources"] = {"piano": proof, "piano_source_revision": PIANO_REV,
                               "piano_record_sha256": file_hash(meta_path),
                               "basic_pitch_sha256": file_hash(asset)}
    started = time.perf_counter()
    crnn = PianoTranscription(checkpoint_path=str(checkpoint), device="cpu")
    basic = Model(str(asset))
    # Keep the same CPU provider, with explicit thread bounds rather than ambient cores.
    options = ort.SessionOptions()
    options.intra_op_num_threads, options.inter_op_num_threads = 2, 1
    basic.model = ort.InferenceSession(str(asset), sess_options=options, providers=["CPUExecutionProvider"])
    report["model_loading_seconds"] = time.perf_counter() - started
    code, code_proof = pinned_source(work, "calebyhan/rescored", RESCORED_REV,
                                    "backend/refinement/bilstm_refiner.py",
                                    "3f545b1e2e9cfaa97a34c02ac7253ff72b75e85f", 14755)
    weights, weights_proof = pinned_source(work, "calebyhan/rescored", RESCORED_REV,
                                          "backend/refinement/checkpoints/bilstm_best.pt",
                                          "91b7365d9461c3181542addce8a776a7143e4296", 9762437)
    report["model_sources"]["bilstm"] = {"code": code_proof, "weights": weights_proof}
    spec = importlib.util.spec_from_file_location("reviewed_bilstm", code)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    refiner = module.BiLSTMRefinementPipeline(weights, device="cpu")
    if refiner.model is None:
        raise RuntimeError("No trained BiLSTM; refusing no-op/random fallback")
    fixtures = piano_fixtures(work)
    report["planned_case_ids"] = [a.stem for a, _ in fixtures]
    for audio, truth in fixtures:
        row = {"id": audio.stem, "audio_sha256": file_hash(audio),
               "reference_sha256": file_hash(truth), "models": {}}
        for name in ("piano_crnn", "basic_pitch"):
            output = work / f"{audio.stem}-{name}.mid"
            started = time.perf_counter()
            if name == "piano_crnn":
                y, _ = librosa.load(audio, sr=16000, mono=True)
                crnn.transcribe(y, str(output))
            else:
                _raw, midi, _events = predict(str(audio), basic)
                midi.write(str(output))
            seconds = time.perf_counter() - started
            before = score_midi(truth, output)
            started = time.perf_counter()
            refined = refiner.refine_midi(output, threshold=0.5)
            after = score_midi(truth, Path(refined))
            row["models"][name] = {"raw": before, "bilstm": after,
                                    "inference_seconds": seconds,
                                    "bilstm_seconds": time.perf_counter() - started}
        row["status"] = "scored"
        report["cases"].append(row)
        checkpoint_report(report)
        print("Piano diagnostic scored", row["id"], flush=True)
    report["macro"] = {name: {arm: {metric: mean(
        r["models"][name][arm][metric]["f1"] for r in report["cases"])
        for metric in ("onset", "onset_offset")} for arm in ("raw", "bilstm")}
        for name in ("piano_crnn", "basic_pitch")}


def main() -> int:
    global REPORT_OUTPUT

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", required=True, choices=("piano", "beat_this", "stringnet"))
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    REPORT_OUTPUT = args.report
    root = Path(__file__).resolve().parents[1]
    work = args.work.absolute()
    if work.exists() or work.is_symlink() or work.resolve().is_relative_to(root):
        parser.error("Require a new private directory outside repository")
    work.mkdir(parents=True)
    report = {"schema_version": 1, "candidate": args.candidate, "device": "cpu",
              "seed": 0, "threads": 2, "cases": [], "all_cases_complete": False,
              "heldout_generalization_approved": False, "product_quality_approved": False,
              "media_uploaded": False, "source_code_revision": os.getenv("GITHUB_SHA"),
              "script_sha256": file_hash(Path(__file__)), "python": platform.python_version(),
              "runtime": {d.metadata["Name"]: d.version for d in distributions() if d.metadata["Name"]},
              "blocked_candidates": {
                  "roformer": "exact checkpoint rights/provenance not cleared; no inference",
                  "open_fret": "no verified pretrained weights; no inference"}}
    checkpoint_report(report)
    try:
        import torch

        random.seed(0)
        np.random.seed(0)
        torch.manual_seed(0)
        torch.set_num_threads(2)
        if torch.cuda.is_available() or os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN"):
            raise RuntimeError("CPU/no-model-credential contract violated")
        report["torch"] = torch.__version__
        {"piano": run_piano, "beat_this": run_beats, "stringnet": run_strings}[args.candidate](work, report)
        expected = 3 if args.candidate == "piano" else 6
        if len(report["cases"]) != expected or any(r["status"] != "scored" for r in report["cases"]):
            raise ValueError("Incomplete planned case set")
        report.update(status="complete", all_cases_complete=True)
        return_code = 0
    except Exception as exc:
        report.update(status="failed", error_type=type(exc).__name__, error=str(exc)[:1000])
        report.pop("macro", None)
        print(type(exc).__name__, str(exc)[:1000], file=sys.stderr, flush=True)
        return_code = 1
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({k: report.get(k) for k in ("candidate", "status", "macro")}))
    return return_code


if __name__ == "__main__":
    raise SystemExit(main())
