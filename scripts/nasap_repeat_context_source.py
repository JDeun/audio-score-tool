"""Additional same-written-score sources with explicit CSV serialization checks.

The previous four performances and their adapter remain unchanged. This module
adds the next two metadata-selected exact-XML groups. Canonical times always
come from MusicXML Fractions. CSV decimal times must match those Fractions
exactly or pack to the same IEEE754 binary32 bytes; no tolerance is fitted.
Input preparation remains MIDI plus supplied performance beats only.
"""
from __future__ import annotations

import csv
import io
import json
import math
import re
import struct
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from fractions import Fraction
from pathlib import Path

from scripts import nasap_same_score_source as previous

MANIFEST_PATH = Path(__file__).with_name("nasap_repeat_context_manifest.json")
MANIFEST_SHA256 = "87544fc4e8774a54f63cf49075ddec077171745a12eb98efd43edaa7b97669ba"
REVISION = previous.REVISION
SCOPE = "real_additional_same_score"
LENGTH_Q = 32.0
CASE_PAIRS = (("bwv_857", "Bult-ItoS02M"), ("bwv_857", "Lan01M"),
              ("bwv_858", "VuV01M"), ("bwv_858", "Zhang01M"))
TIMING_FIELDS = ("onset_quarter", "duration_quarter", "onset_beat", "duration_beat")
INHERITED_PATHS = ("scripts/nasap_same_score_source.py", "scripts/same_score_phase.py",
                   *previous.PARSER_PATHS)
AdmissionError = previous.AdmissionError
sha256 = previous.sha256
fingerprint = previous.fingerprint


def validate_manifest(manifest):
    require = previous._require
    require(manifest.get("schema_version") == 1 and manifest.get("revision") == REVISION
            and manifest.get("source_base") == previous.SOURCE_BASE
            and manifest.get("license") == "CC-BY-NC-SA-4.0", "additional source identity changed")
    cases, members = manifest.get("cases", []), manifest.get("members", {})
    require(len(cases) == 4 and len(members) == 25, "additional source population changed")
    expected_paths, input_paths = {"metadata.csv"}, set()
    for i, (case, (piece, take)) in enumerate(zip(cases, CASE_PAIRS)):
        prefix = "Bach/Fugue/" + piece + "/"
        paths = {"midi": prefix + take + ".mid",
                 "performance_annotations": prefix + take + "_annotations.txt",
                 "xml": prefix + "xml_score.musicxml",
                 "score_annotations": prefix + "midi_score_annotations.txt",
                 "part": prefix + take + "_note_alignments/parangonada_data/part.csv",
                 "ppart": prefix + take + "_note_alignments/parangonada_data/ppart.csv",
                 "alignment": prefix + take + "_note_alignments/note_alignment.tsv"}
        require(case.get("id") == f"nasap{i + 5:03d}"
                and case.get("performance_id") == case["id"]
                and case.get("score_id") == f"score{i // 2 + 3:03d}"
                and all(case.get(k) == v for k, v in paths.items()),
                "additional case identity or order changed")
        expected_paths.update(paths.values())
        input_paths.update(case[k] for k in previous.INPUT_FIELDS)
    require(set(members) == expected_paths, "additional source member set changed")
    for path, member in members.items():
        previous._safe_path(path)
        require(set(member) == {"bytes", "sha256"}
                and type(member["bytes"]) is int and 0 < member["bytes"] <= previous.MAX_FILE_BYTES
                and isinstance(member["sha256"], str)
                and re.fullmatch(r"[0-9a-f]{64}", member["sha256"]), "invalid additional member")
    require(members["metadata.csv"] == {"bytes": 616855, "sha256": previous.METADATA_SHA256},
            "pinned metadata identity changed")
    require(manifest.get("budget") == {"member_count": 25, "total_bytes": 2360916,
            "input_member_count": 8, "input_bytes": 69674, "maximum_member_bytes": 4000000}
            and sum(m["bytes"] for m in members.values()) == 2360916
            and sum(members[p]["bytes"] for p in input_paths) == 69674,
            "additional source budget changed")
    selection = manifest.get("selection", {})
    require(selection.get("scope") == SCOPE and selection.get("planned_recordings") == 4
            and selection.get("planned_scores") == 2 and selection.get("length_q") == LENGTH_Q
            and selection.get("score_origin_q") == 4.0 and selection.get("meter") == "4/4"
            and selection.get("bars") == 8 and selection.get("replacements") == []
            and selection.get("model_inference_before_freeze") is False,
            "additional selection contract changed")
    evidence = manifest.get("selection_before_source_read", {})
    evidence_bytes = (json.dumps(evidence, indent=2) + "\n").encode()
    require(sha256(evidence_bytes) == manifest.get("selection_before_source_read_sha256")
            and evidence.get("source_outcomes_inspected") is False
            and evidence.get("model_inferences") == 0
            and evidence.get("selected_rows") == [c["metadata_row"] for c in cases],
            "before-source metadata selection evidence changed")
    require(set(manifest.get("parser_dependencies", {})) == set(previous.PARSER_PATHS)
            and set(manifest.get("inherited_source_sha256", {})) == set(INHERITED_PATHS)
            and manifest.get("mido_version") == "1.3.3", "inherited dependency set changed")


def load_manifest():
    raw = MANIFEST_PATH.read_bytes()
    previous._require(len(raw) <= 100000 and sha256(raw) == MANIFEST_SHA256,
                      "additional manifest digest mismatch")
    manifest = json.loads(raw)
    validate_manifest(manifest)
    root = Path(__file__).resolve().parents[1]
    for path, digest in manifest["inherited_source_sha256"].items():
        previous._require(sha256((root / path).read_bytes()) == digest,
                          "inherited source dependency changed")
    return manifest


class SourceReader(previous.SourceReader):
    """Reuse the unchanged exact-byte transport, with this manifest's identity."""

    def receipt(self, stage, cases):
        value = super().receipt(stage, cases)
        value.update(manifest_sha256=MANIFEST_SHA256, scope=SCOPE,
                     selection_before_source_read_sha256=self.manifest["selection_before_source_read_sha256"])
        return value


def prepare_inputs(work):
    manifest = load_manifest()
    reader, cases = SourceReader(work, manifest), []
    for case in manifest["cases"]:
        try:
            midi = reader.get(case["midi"])
            annotation = reader.get(case["performance_annotations"])
            events, _, receipt = previous.parse_input(midi, annotation)
            cases.append({"id": case["id"], "status": "complete", "scope": SCOPE,
                          "events": events, "length_q": LENGTH_Q, "receipt": receipt})
        except AdmissionError as exc:
            failed = previous._failed(case["id"], exc)
            failed["scope"] = SCOPE
            cases.append(failed)
    return {"cases": cases, "source_receipt": reader.receipt("inputs", cases)}


def _verify_metadata(raw, manifest):
    previous._require(sha256(raw) == previous.METADATA_SHA256, "additional metadata digest mismatch")
    rows = list(csv.DictReader(io.StringIO(raw.decode("utf-8-sig"))))
    by_id = {r["midi_performance"]: r for r in rows}
    previous._require(len(rows) == len(by_id) == 1066, "metadata population changed")
    groups = defaultdict(set)
    for row in rows:
        if (row.get("robust_note_alignment") in ("1", "1.0")
                and row.get("xml_score", "").startswith("Bach/Fugue/")
                and all(row.get(k) for k in ("note_alignments", "parangonada_data_folder",
                                             "performance_annotations"))):
            groups[row["xml_score"]].add(row["midi_performance"])
    selected_groups = sorted(path for path, members in groups.items()
                             if path > "Bach/Fugue/bwv_854/xml_score.musicxml" and len(members) >= 2)[:2]
    selected_midi = [path for group in selected_groups for path in sorted(groups[group])[:2]]
    previous._require(selected_midi == [c["midi"] for c in manifest["cases"]]
                      and selected_groups == manifest["selection_before_source_read"]["selected_groups"],
                      "deterministic additional cohort selection changed")
    for case in manifest["cases"]:
        previous._require(by_id[case["midi"]] == case["metadata_row"], "additional metadata row changed")


def _pitch(node):
    pitch = node.find("pitch")
    previous._admit(pitch is not None, "unpitched_grace_not_supported")
    return (12 * (int(pitch.findtext("octave")) + 1)
            + {"C": 0, "D": 2, "E": 4, "F": 5, "G": 7, "A": 9, "B": 11}[pitch.findtext("step")]
            + int(pitch.findtext("alter", "0")))


def _exact_graces(root, parsed):
    """Retain Fraction positions instead of converting grace positions to floats."""
    starts = {(m["part"], m["index"]): m["start"] for m in parsed["measures"]}
    answer = {}
    for part in root.findall("part"):
        division = None
        for index, measure in enumerate(part.findall("measure")):
            cursor, previous_start = Fraction(0), None
            absolute = starts[part.get("id"), index]
            for node in measure:
                if node.tag == "attributes" and node.find("divisions") is not None:
                    division = int(node.findtext("divisions"))
                elif node.tag in ("backup", "forward"):
                    value = Fraction(int(node.findtext("duration")), division)
                    cursor += value if node.tag == "forward" else -value
                elif node.tag == "note":
                    if node.find("grace") is not None:
                        previous._admit(node.find("chord") is None, "grace_chord_not_supported")
                        nid = node.get("id")
                        previous._admit(bool(nid) and nid not in answer, "invalid_grace_identity")
                        answer[nid] = {"onset": absolute + cursor, "duration": Fraction(0),
                                       "pitch": _pitch(node), "grace": True,
                                       "voice": node.findtext("voice", "1")}
                    else:
                        duration = Fraction(int(node.findtext("duration")), division)
                        start = previous_start if node.find("chord") is not None else cursor
                        if node.find("chord") is None:
                            previous_start, cursor = start, start + duration
    previous._admit(len(answer) == len(parsed["grace"]), "grace_inventory_mismatch")
    return answer


def serialization_kind(actual, expected):
    """A discrete serialization identity check, never a floating tolerance."""
    try:
        actual = Fraction(actual)
        expected = Fraction(expected)
        if actual == expected:
            return "exact"
        left, right = float(actual), float(expected)
        previous._admit(math.isfinite(left) and math.isfinite(right), "nonfinite_canonical_scalar")
        if struct.pack("!f", left) == struct.pack("!f", right):
            return "binary32"
    except (ValueError, TypeError, OverflowError, struct.error, ZeroDivisionError) as exc:
        if isinstance(exc, AdmissionError):
            raise
        raise AdmissionError("invalid_canonical_scalar") from exc
    raise AdmissionError("canonical_serialization_mismatch")


def canonical_score(raw_xml, part_rows, parser):
    """Validate every score row; only unchanged XML Fractions become targets."""
    try:
        parsed = parser(raw_xml)
        root = ET.fromstring(raw_xml)
        previous._admit(not root.findall(".//repeat"), "repeat_occurrences_not_supported")
        previous._admit(all(m["simple_full"] and m["nominal"] == 4 for m in parsed["measures"]),
                        "unsupported_score_meter_or_pickup")
        previous._admit(any(m["start"] == 4 for m in parsed["measures"]),
                        "canonical_bar_origin_not_structural")
        expected = {nid: {"onset": n["start"], "duration": n["end"] - n["start"],
                          "pitch": n["pitch"], "grace": False, "voice": n["voice"][1]}
                    for nid, n in parsed["notes"].items()}
        graces = _exact_graces(root, parsed)
        previous._admit(not set(graces) & set(expected), "duplicate_ordinary_grace_identity")
        expected.update(graces)
        try:
            previous.canonical_score(raw_xml, part_rows, lambda _: parsed)
            old_failure = None
        except AdmissionError as exc:
            old_failure = exc.code
            if old_failure != "xml_csv_canonical_mismatch":
                raise
        canonical, exact, binary32 = {}, 0, 0
        differences, mismatched_notes, inside, outside = Counter(), set(), 0, 0
        max_difference = Fraction(0)
        for row in part_rows:
            nid, suffix = row["id"].rsplit("-", 1)
            previous._admit(suffix == "1" and nid in expected and row["id"] not in canonical,
                            "unsupported_or_duplicate_score_occurrence")
            note = expected[nid]
            previous._admit(int(row["pitch"]) == note["pitch"], "score_pitch_identity_mismatch")
            previous._admit(str(row["voice"]) == str(note["voice"]), "score_voice_identity_mismatch")
            for field in TIMING_FIELDS:
                target = note["onset"] if field.startswith("onset") else note["duration"]
                kind = serialization_kind(row[field], target)
                if kind == "exact":
                    exact += 1
                else:
                    binary32 += 1
                    differences[field] += 1
                    mismatched_notes.add(row["id"])
                    max_difference = max(max_difference, abs(Fraction(row[field]) - target))
                    if Fraction(4) <= note["onset"] < Fraction(36):
                        inside += 1
                    else:
                        outside += 1
            canonical[row["id"]] = {k: note[k] for k in ("onset", "duration", "pitch", "grace")}
        previous._admit(len(canonical) == len(expected), "incomplete_canonical_score_map")
        receipt = {
            "contract": "exact_fraction_or_identical_ieee754_binary32_bytes",
            "canonical_truth": "unchanged_musicxml_fractions",
            "absolute_or_relative_tolerance_used": False,
            "checked_score_attacks": len(canonical), "checked_timing_scalars": exact + binary32,
            "exact_timing_scalars": exact, "exact_fraction_mismatches": binary32,
            "binary32_admitted_timing_scalars": binary32,
            "exact_mismatch_fields": dict(sorted(differences.items())),
            "exact_mismatch_note_count": len(mismatched_notes),
            "exact_mismatch_note_ids_sha256": fingerprint(sorted(mismatched_notes)),
            "max_abs_difference_q": float(max_difference),
            "mismatches_inside_evaluation_window": inside,
            "mismatches_outside_evaluation_window": outside,
            "all_mismatches_outside_evaluation_window": outside == binary32 if binary32 else None,
            "previous_strict_canonical_status": "failed" if old_failure else "passed",
            "previous_strict_failure_reason": old_failure,
            "id_pitch_voice_tie_checks_unchanged_or_stricter": True,
        }
        return canonical, receipt
    except (ValueError, TypeError, KeyError, ET.ParseError) as exc:
        if isinstance(exc, AdmissionError):
            raise
        raise AdmissionError("unsupported_xml_or_canonical_schema") from exc


def load_evaluation(work, cases):
    """Load score/alignment only after the caller has frozen all predictions."""
    manifest = load_manifest()
    previous._require([c.get("id") for c in cases] == [c["id"] for c in manifest["cases"]],
                      "additional evaluation population changed")
    reader = SourceReader(work, manifest)
    payloads, unavailable = {}, set()
    for path in manifest["members"]:
        try:
            payloads[path] = reader.get(path)
        except AdmissionError:
            unavailable.add(path)
    if "metadata.csv" in payloads:
        _verify_metadata(payloads["metadata.csv"], manifest)
    parser = previous._parser(manifest)
    results, maps = {}, {}
    for case, original in zip(manifest["cases"], cases):
        try:
            previous._admit("metadata.csv" not in unavailable
                            and not any(case[k] in unavailable for k in previous.PATH_FIELDS),
                            "evaluation_source_unavailable")
            previous._admit(original.get("status") == "complete", "input_admission_failed")
            events, state, input_receipt = previous.parse_input(payloads[case["midi"]],
                                                               payloads[case["performance_annotations"]])
            previous._require(tuple(original["events"]) == events
                              and original["receipt"]["input_events_sha256"] == input_receipt["input_events_sha256"],
                              "saved additional inputs changed from original source")
            part = previous._rows(payloads[case["part"]], previous.PART_FIELDS)
            performance = previous._rows(payloads[case["ppart"]], previous.PPART_FIELDS)
            alignment = previous._rows(payloads[case["alignment"]], previous.ALIGNMENT_FIELDS, "\t")
            canonical, serialization = canonical_score(payloads[case["xml"]], part, parser)
            result = previous.evaluate_source({**case, "xml_sha256": sha256(payloads[case["xml"]])},
                state, canonical, part, performance, alignment, payloads[case["score_annotations"]])
            result["receipt"]["canonical_serialization"] = serialization
            results[case["id"]], maps[case["id"]] = result, canonical
        except AdmissionError as exc:
            results[case["id"]] = {"id": case["id"], "status": "failed", "score_id": case["score_id"],
                "performance_id": case["performance_id"], "receipt": {
                    "status": "failed", "failure": exc.code, "diagnostics": exc.diagnostics}}
    verified = 0
    for a, b in (("nasap005", "nasap006"), ("nasap007", "nasap008")):
        if a in maps and b in maps:
            if maps[a] != maps[b]:
                for cid in (a, b):
                    results[cid] = {"id": cid, "status": "failed", "receipt": {
                        "status": "failed", "failure": "paired_canonical_maps_disagree"}}
            else:
                verified += 1
    source_receipt = reader.receipt("evaluation", list(results.values()))
    source_receipt.update(same_score_canonical_pairs_verified=verified,
        parser_dependencies=dict(manifest["parser_dependencies"]),
        inherited_source_sha256=dict(manifest["inherited_source_sha256"]),
        metadata_selection_verified="metadata.csv" not in unavailable)
    return {"cases": results, "source_receipt": source_receipt}
