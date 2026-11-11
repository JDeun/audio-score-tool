"""Paired, score-owned exploratory performance/notation study for issue #249.

Never claim the authored signals are real performances or that a fixed clock
was inferred from audio. No reference enters either score-selection function.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import platform
import random
import time
from dataclasses import asdict
from pathlib import Path
from statistics import mean

from scripts.bar_sum_articulation import (
    extract_audio_accents,
    gate_model_settings,
    search_articulation_phases,
    sha256_audio,
    solve_articulation,
    synthetic_beat_audio,
)
from scripts.bar_sum_rhythm import (
    search_phases,
    solve,
    structural_check,
)
from scripts.run_bar_sum_rhythm import (
    PROFILES,
    authored_scores,
    fingerprint,
    notation_metrics,
    performance,
)

NEW_PROFILES = ("mixed_gate", "variable_short_gate")
ALL_PROFILES = PROFILES + NEW_PROFILES
KNOWN = ("old_joint_notation", "articulation_joint")
UNKNOWN = (
    "old_no_accent", "articulation_no_accent",
    "old_audio_accent", "articulation_audio_accent",
)
ARMS = KNOWN + UNKNOWN


def new_performance(score, profile):
    """Generate previously untested mixed gate patterns; not held-out real data."""
    if profile not in NEW_PROFILES:
        raise ValueError("unknown generated profile")
    seed = int(hashlib.sha256((score["name"] + "/" + profile).encode()).hexdigest()[:16], 16)
    rng = random.Random(seed)
    from scripts.bar_sum_rhythm import Observation

    events = []
    true_clock = score["clock"]
    for note in score["notes"]:
        if profile == "variable_short_gate":
            gate = rng.uniform(.48, .78)
            onset_perturb = rng.uniform(-1.1, 1.1)
        else:
            gate = rng.uniform(.48, 1.06)
            onset_perturb = rng.uniform(-1.4, 1.4)
        observed_start = max(0.0, note.start + onset_perturb)
        observed_end = max(
            observed_start + .25, note.start + gate * note.duration
            + rng.uniform(-1.2, 1.2)
        )
        events.append(Observation(
            note.id, note.pitch, observed_start * true_clock.tick_seconds,
            observed_end * true_clock.tick_seconds
        ))
    return tuple(events), seed


def assess(phrase, profile):
    """Both algorithms see identical events, clock and waveform-derived accents."""
    if profile in PROFILES:
        observations, _idealized_accents, seed = performance(phrase, profile)
    else:
        observations, seed = new_performance(phrase, profile)
    clock, truth = phrase["clock"], phrase["notes"]
    truth_fingerprint = fingerprint([asdict(n) for n in truth])
    inp = fingerprint([asdict(o) for o in observations])

    waveform = synthetic_beat_audio(
        clock, phrase["phase"], phrase["authored_length"], seed
    )
    accents, energy = extract_audio_accents(
        waveform, clock, phrase["authored_length"]
    )
    evidence_fingerprint = fingerprint(accents)

    rows = {}
    baseline_correct = set()
    for name in KNOWN:
        result = (
            solve(observations, clock, phrase["phase"], "joint_notation")
            if name == KNOWN[0]
            else solve_articulation(observations, clock, phrase["phase"]).solution
        )
        metrics = notation_metrics(result.notes, truth)
        matched = set(metrics["correct_note_ids"])
        if name == KNOWN[0]:
            baseline_correct = matched
        rows[name] = {
            "status": "scored",
            "truth_phase_provided": True,
            "metrics": metrics,
            "gained_correct_ids": len(matched - baseline_correct),
            "lost_correct_ids": len(baseline_correct - matched),
            "structure": structural_check(result, clock, observations),
            "notes": [asdict(n) for n in result.notes],
            "search_cost": result.cost,
        }

    for name, observation_accents, articulation in (
        (UNKNOWN[0], (), False),
        (UNKNOWN[1], (), True),
        (UNKNOWN[2], accents, False),
        (UNKNOWN[3], accents, True),
    ):
        outcome = (
            search_articulation_phases(observations, clock, observation_accents)
            if articulation else search_phases(observations, clock, observation_accents)
        )
        selected = outcome["selected_phase"]
        rows[name] = {
            "status": "scored",
            "truth_phase_provided": False,
            "decided": selected is not None,
            "phase_correct": selected == phrase["phase"] if selected is not None else None,
            "selected_phase": selected,
            "candidate_phases": outcome["candidate_phases"],
            "truth_in_candidate_set": phrase["phase"] in outcome["candidate_phases"],
            "runner_up_margin": outcome["runner_up_margin"],
            "best_is_only_diagnostic_if_abstained": selected is None,
            "metrics_if_decided": (
                notation_metrics(outcome["best"].notes, truth)
                if selected is not None else None
            ),
        }

    if (inp != fingerprint([asdict(o) for o in observations])
            or truth_fingerprint != fingerprint([asdict(n) for n in truth])
            or evidence_fingerprint != fingerprint(accents)
            or len(energy) != phrase["authored_length"] + 1):
        raise ValueError("source observation or evidence changed")

    return {
        "id": phrase["name"] + "/" + profile, "phrase": phrase["name"],
        "profile": profile, "status": "scored", "seed": seed,
        "observation_sha256": inp, "reference_sha256": truth_fingerprint,
        "audio_sha256": sha256_audio(waveform), "accent_sha256": evidence_fingerprint,
        "audio_accent_count": len(accents),
        "audio_generation": "other-part synthesized wave; no source recording",
        "clock": asdict(clock), "true_phase_ticks": phrase["phase"],
        "note_count": len(observations), "arms": rows,
    }


def aggregate(rows, planned):
    if (len(rows) != len(planned) or {r["id"] for r in rows} != set(planned)
            or any(r.get("status") != "scored" or set(r.get("arms", {})) != set(ARMS)
                   for r in rows)):
        return None
    output = {"case_count": len(rows), "note_observations": sum(x["note_count"] for x in rows)}
    for arm in KNOWN:
        metrics = [x["arms"][arm]["metrics"] for x in rows]
        output[arm] = {
            k: mean(m[k] for m in metrics)
            for k in ("onset_exact", "duration_exact", "note_pair_exact", "rest_interval_f1")
        }
        output[arm].update(
            structurally_valid=sum(x["arms"][arm]["structure"]["bar_sums_exact"] for x in rows),
            all_notes_exact=sum(m["all_notes_exact"] for m in metrics),
            gains=sum(x["arms"][arm]["gained_correct_ids"] for x in rows),
            losses=sum(x["arms"][arm]["lost_correct_ids"] for x in rows),
        )
    base = KNOWN[0]
    art = KNOWN[1]
    output["paired_changes"] = {
        "better_cases": sum(x["arms"][art]["metrics"]["note_pair_exact"]
                            > x["arms"][base]["metrics"]["note_pair_exact"] + 1e-12
                            for x in rows),
        "worse_cases": sum(x["arms"][art]["metrics"]["note_pair_exact"]
                           < x["arms"][base]["metrics"]["note_pair_exact"] - 1e-12
                           for x in rows),
        "equal_cases": sum(abs(x["arms"][art]["metrics"]["note_pair_exact"]
                               - x["arms"][base]["metrics"]["note_pair_exact"]) <= 1e-12
                           for x in rows),
        "by_profile": {},
    }
    for profile in ALL_PROFILES:
        group = [x for x in rows if x["profile"] == profile]
        output["paired_changes"]["by_profile"][profile] = {
            "cases": len(group),
            "baseline_pair_exact": mean(x["arms"][base]["metrics"]["note_pair_exact"]
                                        for x in group),
            "articulation_pair_exact": mean(x["arms"][art]["metrics"]["note_pair_exact"]
                                            for x in group),
            "gains": sum(x["arms"][art]["gained_correct_ids"] for x in group),
            "losses": sum(x["arms"][art]["lost_correct_ids"] for x in group),
        }
    for name in UNKNOWN:
        values = [x["arms"][name] for x in rows]
        correct = sum(x["phase_correct"] is True for x in values)
        wrong = sum(x["phase_correct"] is False for x in values)
        decided = correct + wrong
        output[name] = {
            "correct_phase": correct,
            "wrong_phase": wrong,
            "abstained": len(rows) - decided,
            "decided": decided,
            "true_phase_in_candidate_set": sum(x["truth_in_candidate_set"] for x in values),
            "conditional_accuracy": correct / decided if decided else None,
            "correct_and_decided_rate": correct / len(rows),
        }
    output["accent_coverage"] = {
        "cases_with_detected_accent": sum(x["audio_accent_count"] > 0 for x in rows),
        "min_detected_accents": min(x["audio_accent_count"] for x in rows),
        "max_detected_accents": max(x["audio_accent_count"] for x in rows),
    }
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.is_symlink() or args.output.exists():
        parser.error("output must be a new, unlinked file")
    repo = Path(__file__).resolve().parents[1]
    paths = (
        "scripts/bar_sum_rhythm.py", "scripts/run_bar_sum_rhythm.py",
        "scripts/bar_sum_articulation.py", "scripts/run_bar_sum_articulation.py",
        "tests/test_bar_sum_articulation.py",
        "docs/research/BAR_SUM_ARTICULATION_PROTOCOL_2026-11-11.md",
    )
    phrases = authored_scores()
    planned = [s["name"] + "/" + p for s in phrases for p in ALL_PROFILES]
    report = {
        "status": "running",
        "scope": "authored notation & generated performance observations, plus synthetic audio accents",
        "source_revision": os.getenv("GITHUB_SHA", "local"),
        "python": platform.python_version(),
        "source_sha256": {
            p: hashlib.sha256((repo / p).read_bytes()).hexdigest() for p in paths
        },
        "settings": gate_model_settings(),
        "settings_sha256": fingerprint(gate_model_settings()),
        "planned_ids": planned,
        "cases": [], "all_cases_complete": False,
        "aggregate": None, "real_recordings": False, "learned_model": False,
        "reference_used_in_selector": False,
        "first_three_arms_receive_true_phase": False,
        "known_phase_arms_have_true_phase": True,
        "quality_approved": False,
        "accuracy_units": "symbolic-written-onset-and-duration, NOT note AMT F1",
        "training": False,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)

    def save():
        temp = args.output.with_suffix(".tmp")
        temp.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        temp.replace(args.output)

    save()
    started = time.monotonic()
    for phrase in phrases:
        for profile in ALL_PROFILES:
            case_id = phrase["name"] + "/" + profile
            try:
                row = assess(phrase, profile)
            except Exception as e:
                row = {"id": case_id, "status": "failed", "error_type": type(e).__name__}
            report["cases"].append(row)
            save()
            print(case_id, row["status"], flush=True)
    report["aggregate"] = aggregate(report["cases"], planned)
    report["all_cases_complete"] = report["aggregate"] is not None
    report["status"] = "complete" if report["all_cases_complete"] else "incomplete"
    report["elapsed_seconds"] = time.monotonic() - started
    save()
    return 0 if report["all_cases_complete"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
