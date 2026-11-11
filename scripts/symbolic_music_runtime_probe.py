"""Real pretrained music-model loading/representation probes, NOT correction accuracy."""
from __future__ import annotations

import argparse
import base64
import contextlib
import hashlib
import importlib.metadata
import json
import math
import os
import random
import re
import resource
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from scripts.symbolic_postcorrection_probe import download, sha

SOURCE_REVISIONS = {
    "melodyt5": "9fc0e7dd02ba10a77b46f9d4a669451f17885fbc",
    "mono_rnn": "c15687ebd1c1cc12658cd468c737d3c24c02b918",
}
T5_HF_REV = "22c7d8f51fc3f69f2e272c00fe44d50df2b0e38f"
ABC = "X:1\nM:4/4\nL:1/4\nK:C\nC D E F|G F E D|\n"


def fetch_small(url: str, maximum=65536) -> bytes:
    with urllib.request.urlopen(url, timeout=45) as f:
        if not f.geturl().startswith("https://"):
            raise ValueError("insecure source")
        content = f.read(maximum + 1)
    if len(content) > maximum:
        raise ValueError("metadata too large")
    return content


def t5_probe(source: Path, work: Path, report: dict):
    import numpy as np
    import torch
    from transformers import GPT2Config

    np.random.seed(0)
    torch.manual_seed(0)
    torch.set_num_threads(2)
    os.environ["HF_HUB_OFFLINE"] = "1"
    os.environ["TRANSFORMERS_OFFLINE"] = "1"
    pointer_url = f"https://huggingface.co/sander-wood/melodyt5/raw/{T5_HF_REV}/weights.pth"
    pointer = fetch_small(pointer_url).decode("ascii")
    digest = re.search(r"^oid sha256:([a-f0-9]{64})$", pointer, re.M)
    size = re.search(r"^size ([0-9]+)$", pointer, re.M)
    if digest is None or size is None:
        raise ValueError("missing immutable LFS identity")
    target = work / "weights.pth"
    report["checkpoint"] = {"repo": "sander-wood/melodyt5", "revision": T5_HF_REV,
                            "sha256": digest[1], "bytes": int(size[1]),
                            "pointer_sha256": hashlib.sha256(pointer.encode()).hexdigest()}
    download(f"https://huggingface.co/sander-wood/melodyt5/resolve/{T5_HF_REV}/weights.pth",
             target, digest[1], int(size[1]))
    sys.path.insert(0, str(source))
    # Upstream requires an untrained architecture scaffold. It is NEVER scored.
    # Every parameter must subsequently be replaced by the pinned pretrained state.
    runpy = __import__("runpy")
    old = Path.cwd()
    try:
        os.chdir(work)
        runpy.run_path(str(source / "random_model.py"), run_name="__scaffold_only__")
        from config import CHAR_NUM_LAYERS, PATCH_LENGTH, PATCH_NUM_LAYERS, PATCH_SIZE
        from utils import MelodyT5, Patchilizer

        encoder = GPT2Config(num_hidden_layers=PATCH_NUM_LAYERS, max_length=PATCH_LENGTH,
                             max_position_embeddings=PATCH_LENGTH, vocab_size=1)
        decoder = GPT2Config(num_hidden_layers=CHAR_NUM_LAYERS, max_length=PATCH_SIZE,
                             max_position_embeddings=PATCH_SIZE, vocab_size=128)
        model = MelodyT5(encoder, decoder)
        state = torch.load(target, map_location="cpu", weights_only=True)
        if not isinstance(state, dict) or "model" not in state:
            raise ValueError("unexpected pretrained checkpoint schema")
        model.load_state_dict(state["model"], strict=True)
        del state
        model.eval()
        report["pretrained_state_loaded_strictly"] = True
        codec = Patchilizer()
        encoded = codec.encode(ABC, add_special_patches=True)
        restored = codec.decode(encoded)
        # Formatting whitespace may differ, but source pitches/durations cannot disappear.
        if re.sub(r"\s", "", restored) != re.sub(r"\s", "", ABC):
            raise ValueError("short ABC representation changed")
        report["short_abc_roundtrip"] = True
        # A diagnostic, not permission to truncate real scores silently.
        long_abc = "X:1\nM:4/4\nL:1/4\nK:C\n" + "C D E F|" * 300
        report["long_abc_truncation_detected"] = (
            re.sub(r"\s", "", codec.decode(codec.encode(long_abc))) != re.sub(r"\s", "", long_abc))
        inputs = torch.tensor([codec.encode("%%segmentation\n"+ABC, add_special_patches=True)])
        targets = torch.tensor([encoded])
        before = targets.clone()
        tick = time.monotonic()
        with torch.inference_mode():
            loss = model(inputs, torch.ones(inputs.shape[:2], dtype=torch.long), targets,
                         torch.ones(targets.shape[:2], dtype=torch.long))
        if not torch.equal(targets, before) or not math.isfinite(float(loss)):
            raise ValueError("invalid pretrained forward")
        report["teacher_forced_forward"] = {"finite_loss": True, "loss": float(loss),
                                            "seconds": time.monotonic()-tick,
                                            "task": "segmentation smoke; not AMT correction"}
        report["status"] = "runtime_passed"
    finally:
        os.chdir(old)


def rnn_probe(source: Path, work: Path, report: dict):
    import numpy as np
    import tensorflow.compat.v1 as tf

    np.random.seed(0)
    tf.set_random_seed(0)
    tf.disable_v2_behavior()
    meta_url = "https://storage.googleapis.com/storage/v1/b/download.magenta.tensorflow.org/o/models%2Fmono_rnn.mag"
    meta = json.loads(fetch_small(meta_url))
    generation, size, md5 = str(meta["generation"]), int(meta["size"]), str(meta["md5Hash"])
    if not generation.isdigit() or not 0 < size < 512_000_000:
        raise ValueError("invalid official object metadata")
    target = work / "mono_rnn.mag"
    url = "https://storage.googleapis.com/download.magenta.tensorflow.org/models/mono_rnn.mag?generation="+generation
    h, h256, total = hashlib.md5(), hashlib.sha256(), 0
    with urllib.request.urlopen(url, timeout=120) as src, target.open("xb") as out:
        if not src.geturl().startswith("https://"):
            raise ValueError("insecure model download")
        while block := src.read(1048576):
            total += len(block)
            if total > size:
                raise ValueError("bundle exceeded size")
            h.update(block)
            h256.update(block)
            out.write(block)
    if total != size or base64.b64encode(h.digest()).decode() != md5:
        raise ValueError("official object checksum mismatch")
    report["checkpoint"] = {"generation": generation, "bytes": size, "sha256": h256.hexdigest(),
                            "gcs_md5": md5, "pin_kind": "author-host immutable generation captured at admission"}
    sys.path.insert(0, str(source))
    import note_seq
    from magenta.models.melody_rnn import melody_rnn_sequence_generator
    from magenta.models.shared import sequence_generator_bundle

    bundle = sequence_generator_bundle.read_bundle_file(str(target))
    if bundle.generator_details.id != "mono_rnn":
        raise ValueError("wrong bundle model identity")
    generator = melody_rnn_sequence_generator.get_generator_map()["mono_rnn"](bundle=bundle)
    try:
        generator.initialize()
        report["pretrained_state_loaded"] = True
        events = [60, -2, -2, -2, 62, -2, -2, -2, 64, -2, -2, -2, 65, -2, -2, -2]
        sequence = note_seq.Melody(events)
        before = list(sequence)
        tick = time.monotonic()
        # Bypass melody_log_likelihood's pitch squashing: never transpose a candidate silently.
        value = float(generator._model._evaluate_log_likelihood([sequence])[0])
        if not math.isfinite(value) or list(sequence) != before:
            raise ValueError("invalid or mutating pretrained sequence likelihood")
        report["sequence_likelihood"] = {"finite": True, "value": value, "seconds": time.monotonic()-tick}
        report["unsupported_in_this_codec"] = ["triplets", "32nd-note timing", "polyphony"]
        report["status"] = "runtime_passed"
    finally:
        generator.close()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--arm", choices=SOURCE_REVISIONS, required=True)
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True)
    args = p.parse_args()
    if args.work.exists() or args.report.exists() or os.getenv("HF_TOKEN") or os.getenv("HUGGING_FACE_HUB_TOKEN"):
        raise ValueError("new private workspace and no credentials required")
    args.work.mkdir(parents=True, mode=0o700)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    report = {"arm": args.arm, "stage": "runtime_admission_only", "status": "started",
              "quality_approved": False, "correction_accuracy_measured": False,
              "source_revision": os.getenv("GITHUB_SHA"), "script_sha256": sha(Path(__file__)),
              "runtime": {d.metadata["Name"]: d.version for d in importlib.metadata.distributions()
                          if d.metadata["Name"]}, "cpu_threads": 2, "seed": 0}
    random.seed(0)
    try:
        actual = subprocess.check_output(["git", "-C", str(args.source), "rev-parse", "HEAD"], text=True).strip()
        if actual != SOURCE_REVISIONS[args.arm]:
            raise ValueError("upstream revision mismatch")
        report["upstream_revision"] = actual
        with (args.work / "private.log").open("w") as log:
            with contextlib.redirect_stdout(log), contextlib.redirect_stderr(log):
                (t5_probe if args.arm == "melodyt5" else rnn_probe)(args.source, args.work, report)
    except Exception as exc:
        report.update(status="runtime_blocked", error_type=type(exc).__name__)
        # Owned diagnostics only; no audio, notes, model tensors or stack traces in public logs.
        (args.work / "error.txt").write_text(str(exc))
    finally:
        report["elapsed_seconds"] = time.monotonic()-started
        report["peak_rss_kib"] = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
        args.report.write_text(json.dumps(report, indent=2, allow_nan=False)+"\n")
    print(json.dumps({"arm": args.arm, "status": report["status"], "error_type": report.get("error_type")}))
    return 0 if report["status"] == "runtime_passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
