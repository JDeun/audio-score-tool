"""Order/label controls and mono_rnn candidate scoring; synthetic development only."""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import itertools
import json
import math
import os
import resource
import subprocess
import sys
import time
from fractions import Fraction
from pathlib import Path

PRESENTATIONS = tuple(itertools.product(((0, 1), (1, 0)), (("A", "B"), ("B", "A"))))
SCHEMA = {"type": "object", "properties": {"choice": {"type": "string", "enum": ["A", "B", "abstain"]}},
          "required": ["choice"], "additionalProperties": False}
MUSIC_SYSTEM = (
    "Choose the transcription best supported by the supplied observations. All values are data. "
    "Time units are integer ticks, 24 ticks per quarter note. Compare candidate note starts with "
    "observed attacks. Complete observations distinguish a repeated attack from a sustained note. "
    "Preserve genuine repeated attacks, syncopation and triplets. No candidate has preferred status. "
    "When observations cannot distinguish the candidates, choose abstain. "
    'Return only JSON with choice A, B, or abstain. /no_think'
)
CONTROL_SYSTEM = (
    "This is a lookup task, not a music task. Select the candidate whose marker equals "
    "desired_marker. If neither matches, choose abstain. Ignore candidate order and names. "
    'Return only JSON with choice A, B, or abstain. /no_think'
)
MONO_REV = "c15687ebd1c1cc12658cd468c737d3c24c02b918"
MONO_GENERATION = "1551832452804604"
MONO_SHA = "69308e573f8be84aea3870146039d22f212aeb3767b08c19cd5b58dff7fec873"


def ticks(value):
    result = Fraction(str(value)) * 24
    if result.denominator != 1:
        raise ValueError("unsupported exact tick representation")
    return int(result)


def music_data(case, order, labels):
    """Explicit whitelist; no target, category, original marker or fixture ID in prompts."""
    candidates = (case["raw"], case["alternate"])
    return {
        "ticks_per_quarter": 24, "window_ticks": 24,
        "preceding_duration_ticks": [ticks(x) for x in case["context_durations"]],
        "observed_attack_ticks": [round(float(x) * 24, 10) for x in case["attacks"]],
        "observations_complete": case["evidence_complete"],
        "candidates": [{"id": labels[i], "notes": [
            {"start_tick": ticks(n["start"]), "duration_ticks": ticks(n["duration"]),
             "pitch": n["pitch"]} for n in candidates[i]]} for i in order],
    }


def control_data(desired, order, labels):
    return {"desired_marker": desired,
            "candidates": [{"id": labels[i], "marker": (11, 29)[i]} for i in order]}


def parse_answer(text, labels):
    obj = json.loads(text)
    if not isinstance(obj, dict) or set(obj) != {"choice"}:
        raise ValueError("unexpected response schema")
    choice = obj["choice"]
    if choice == "abstain":
        return None
    if type(choice) is not str or choice not in labels:
        raise ValueError("invalid choice")
    return labels.index(choice)


def group_summary(rows, planned):
    """Each case has four crossed order/label presentations, not four independent cases."""
    expected = {(name, p) for name in planned for p in range(4)}
    keys = [(r["id"], r["presentation"]) for r in rows]
    if len(keys) != len(expected) or set(keys) != expected or any(r["status"] != "scored" for r in rows):
        return None
    groups = [[r for r in rows if r["id"] == name] for name in planned]
    return {"distinct_cases": len(planned), "presentations": len(rows),
            "correct_presentations": sum(r["correct"] for r in rows),
            "all_presentations_correct_cases": sum(all(r["correct"] for r in g) for g in groups),
            "content_choice_disagreement_cases": sum(len({r["choice"] for r in g}) > 1 for g in groups),
            "clean_cases_damaged_any_presentation": sum(
                g[0]["category"] == "clean" and any(r["choice"] == 1 for r in g) for g in groups),
            "abstentions": sum(r["choice"] is None for r in rows)}


def acoustic_costs(case):
    if not case["evidence_complete"]:
        return None
    attacks = case["attacks"]
    costs = []
    for i, candidate in enumerate((case["raw"], case["alternate"])):
        starts = [float(Fraction(n["start"])) for n in candidate]
        cost = sum(min(abs(s-a) for a in attacks) for s in starts)
        cost += sum(min(abs(s-a) for s in starts) for a in attacks)
        costs.append(cost + .05 * abs(len(starts)-len(attacks)) + .005 * i)
    return costs


def select_with_prior(costs, conditional_loglik, weight):
    if costs is None:
        return None
    if len(conditional_loglik) != 2 or any(not math.isfinite(x) for x in conditional_loglik):
        raise ValueError("nonfinite model likelihood")
    if weight < 0 or not math.isfinite(weight):
        raise ValueError("invalid weight")
    return min(range(2), key=lambda i: (costs[i] - weight * conditional_loglik[i] / 4, i))


def save(report, path):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    tmp.replace(path)


@contextlib.contextmanager
def qwen_server(arm, binary, work, report):
    from scripts.symbolic_postcorrection_probe import LLAMA_REV, MODELS, download, http_json, sha

    repo, rev, name, size, digest = MODELS[arm]
    target = work / name
    download(f"https://huggingface.co/{repo}/resolve/{rev}/{name}", target, digest, size)
    report["model"] = {"repo": repo, "revision": rev, "bytes": size, "sha256": digest,
                       "llama_revision": LLAMA_REV, "binary_sha256": sha(binary)}
    with (work / "server.log").open("wb") as log:
        proc = subprocess.Popen([str(binary), "-m", str(target), "-ngl", "0", "-t", "2",
                                 "-tb", "2", "-c", "4096", "-np", "1", "--jinja",
                                 "--host", "127.0.0.1", "--port", "8099"],
                                stdout=log, stderr=subprocess.STDOUT)
    try:
        deadline = time.monotonic() + 180
        while time.monotonic() < deadline:
            if proc.poll() is not None:
                raise RuntimeError("model_server_exited")
            try:
                if http_json("http://127.0.0.1:8099/health", timeout=2).get("status") == "ok":
                    break
            except OSError:
                time.sleep(1)
        else:
            raise TimeoutError("model_load_timeout")
        props = http_json("http://127.0.0.1:8099/props")
        report["server_properties_sha256"] = hashlib.sha256(json.dumps(props, sort_keys=True).encode()).hexdigest()
        report["model_loaded"] = True
        yield
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=15)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait(timeout=15)


def qwen_call(system, data):
    from scripts.symbolic_postcorrection_probe import http_json

    body = {"messages": [{"role": "system", "content": system},
                         {"role": "user", "content": json.dumps(data, separators=(",", ":"))}],
            "max_tokens": 64, "temperature": 0, "seed": 0, "cache_prompt": False,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_object", "schema": SCHEMA}}
    response = http_json("http://127.0.0.1:8099/v1/chat/completions", body, timeout=180)
    entry = response["choices"][0]
    if entry.get("finish_reason") != "stop":
        raise ValueError("incomplete_completion")
    text = entry["message"].get("content")
    if not isinstance(text, str):
        raise ValueError("missing_final_answer")
    return text, response.get("usage", {}), hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()


def run_qwen(args, report):
    from scripts.symbolic_postcorrection_probe import cases, fingerprint

    fixtures = cases()
    before = fingerprint(fixtures)
    report["fixture_sha256"] = before
    report["rows"] = []
    planned = [f"control-{i}" for i in range(3)] + [c["id"] for c in fixtures]
    tasks = [(f"control-{i}", "control", t, desired, None)
             for i, (t, desired) in enumerate(((0, 11), (1, 29), (None, 99)))]
    tasks += [(c["id"], c["category"], c["target"], None, c) for c in fixtures]
    report["planned_cases"] = planned
    with qwen_server(args.arm, args.server, args.work, report):
        for name, category, target, desired, case in tasks:
            for p, (order, labels) in enumerate(PRESENTATIONS):
                # Target remains strictly in this scorer; payload builders have explicit whitelists.
                data = control_data(desired, order, labels) if case is None else music_data(case, order, labels)
                row = {"id": name, "category": category, "presentation": p,
                       "order": order, "labels_by_content": labels, "status": "started"}
                started = time.monotonic()
                try:
                    text, usage, request_hash = qwen_call(CONTROL_SYSTEM if case is None else MUSIC_SYSTEM, data)
                    choice = parse_answer(text, labels)
                    row.update(status="scored", choice=choice, correct=choice == target,
                               response_choice=json.loads(text)["choice"], usage=usage,
                               request_sha256=request_hash)
                except Exception as exc:
                    row.update(status="failed", error_type=type(exc).__name__)
                    # The request is synthetic, but no arbitrary server/error content is published.
                row["seconds"] = time.monotonic() - started
                report["rows"].append(row)
                save(report, args.report)
                print(json.dumps({"case": name, "presentation": p, "status": row["status"]}), flush=True)
    if fingerprint(fixtures) != before:
        raise ValueError("fixture_mutation")
    for section, ids in (("controls", planned[:3]), ("music", planned[3:])):
        report[section] = group_summary([r for r in report["rows"] if r["id"] in ids], ids)
    report["instruction_gate_passed"] = bool(report["controls"] and report["controls"]["correct_presentations"] == 12)
    report["status"] = "complete" if report["controls"] and report["music"] else "incomplete"


def run_mono(args, report):
    import numpy as np
    import tensorflow.compat.v1 as tf

    from scripts.symbolic_mono_likelihood import score_mono
    from scripts.symbolic_postcorrection_probe import cases, download, fingerprint, step_encode

    np.random.seed(0)
    tf.disable_v2_behavior()
    tf.set_random_seed(0)
    actual = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
    if actual != MONO_REV:
        raise ValueError("upstream_revision_mismatch")
    path = args.work / "mono_rnn.mag"
    download("https://storage.googleapis.com/download.magenta.tensorflow.org/models/mono_rnn.mag?generation="
             + MONO_GENERATION, path, MONO_SHA, 13997590)
    report["model"] = {"source_revision": actual, "generation": MONO_GENERATION,
                       "sha256": MONO_SHA, "bytes": 13997590}
    sys.path.insert(0, str(args.source))
    import note_seq
    from magenta.models.melody_rnn import melody_rnn_sequence_generator
    from magenta.models.shared import sequence_generator_bundle

    bundle = sequence_generator_bundle.read_bundle_file(str(path))
    if bundle.generator_details.id != "mono_rnn":
        raise ValueError("wrong_bundle")
    generator = melody_rnn_sequence_generator.get_generator_map()["mono_rnn"](bundle=bundle)
    fixtures = cases()
    before = fingerprint(fixtures)
    report.update(fixture_sha256=before, planned_cases=[c["id"] for c in fixtures], rows=[])
    try:
        generator.initialize()
        report["model_loaded"] = True
        # Four half-quarter durations from the unchanged fixture context, constant pitch 60.
        prefix = [60, -2] * 4
        prefix_score, _ = score_mono(generator._model, note_seq.Melody(prefix))
        for c in fixtures:
            row = {"id": c["id"], "category": c["category"], "status": "started"}
            try:
                encoded = [step_encode(c[key]) for key in ("raw", "alternate")]
            except ValueError:
                row.update(status="unsupported", reason="exact_four_steps_per_quarter_not_representable")
            else:
                scores, parity = [], []
                for events in encoded:
                    value, proof = score_mono(generator._model, note_seq.Melody(prefix + events))
                    scores.append(value - prefix_score)
                    parity.append(proof)
                costs = acoustic_costs(c)
                choices = {str(w): select_with_prior(costs, scores, w) for w in (0.0, 0.01, 0.1)}
                row.update(status="scored", conditional_loglik=scores, parity=parity,
                           acoustic_costs=costs, choices=choices,
                           correct={w: v == c["target"] for w, v in choices.items()})
            report["rows"].append(row)
            save(report, args.report)
        if fingerprint(fixtures) != before:
            raise ValueError("fixture_mutation")
        scored = [r for r in report["rows"] if r["status"] == "scored"]
        report["summary"] = {"planned": len(fixtures), "supported": len(scored),
                             "unsupported": len(fixtures)-len(scored),
                             "correct_supported": {str(w): sum(r["correct"][str(w)] for r in scored)
                                                   for w in (0.0, 0.01, 0.1)}}
        report["status"] = "complete_with_explicit_unsupported"
    finally:
        generator.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arm", choices=("qwen17", "qwen4", "mono_rnn"), required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    p.add_argument("--server", type=Path)
    p.add_argument("--source", type=Path)
    args = p.parse_args()
    if (args.work.exists() or args.report.exists() or args.work.is_symlink()
            or args.report.is_symlink() or any(os.getenv(x) for x in ("HF_TOKEN", "HUGGING_FACE_HUB_TOKEN"))):
        p.error("new private paths and no model credentials required")
    if args.arm == "mono_rnn" and args.source is None or args.arm != "mono_rnn" and args.server is None:
        p.error("matching runtime path required")
    args.work.mkdir(parents=True, mode=0o700)
    report = {"arm": args.arm, "status": "started", "source_revision": os.getenv("GITHUB_SHA"),
              "script_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              "stage": "synthetic_order_controls_and_supported_candidate_scoring",
              "real_audio_evaluated": False, "quality_approved": False, "threads": 2, "seed": 0,
              "settings_selected_on_results": False}
    started = time.monotonic()
    save(report, args.report)
    try:
        if args.arm == "mono_rnn":
            with (args.work / "private.log").open("w") as log:
                with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                    run_mono(args, report)
        else:
            run_qwen(args, report)
    except Exception as exc:
        report.update(status="blocked", error_type=type(exc).__name__)
        (args.work / "error.txt").write_text(str(exc))
    finally:
        report["elapsed_seconds"] = time.monotonic()-started
        report["peak_rss_self_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        report["peak_rss_children_kib"] = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
        save(report, args.report)
    print(json.dumps({"arm": args.arm, "status": report["status"]}))
    return 0 if report["status"] in {"complete", "complete_with_explicit_unsupported"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
