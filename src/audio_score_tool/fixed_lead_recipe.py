"""One versioned vocal recipe; never substitute weights by availability or song."""
from __future__ import annotations

import hashlib
import platform
from importlib.metadata import version
from pathlib import Path

ENGINE = "vocal_lead_v1"
YOUR_VARIANT = "mc13_256_g4_all_v7_mt3f_sqr_rms_moe_wf4_n8k2_silu_rope_rp_b36_nops"
YOUR_CHECKPOINT = Path("yourmt3") / YOUR_VARIANT / "last.ckpt"
YOUR_SHA256 = "ae38e415c79efd5592dcb9b658cdb99ddb11d4c4e1eaa364cab04a052473fc25"
YOUR_REVISION = "5e66c1ea173a8186e0d20432b841d3180cc015b5"
DEMUCS_WEIGHT = "955717e8-8726e21a.th"
DEMUCS_SHA256 = "8726e21a993978c7ba086d3872e7608d7d5bfca646ca4aca459ffda844faa8b4"
YOUR_RUNTIME = {"mt3-infer": "0.2.0", "torch": "2.7.1", "torchaudio": "2.7.1",
                "transformers": "4.44.2", "numpy": "2.4.6", "soundfile": "0.14.0"}
SEPARATOR_RUNTIME = {"demucs": "4.0.1", "julius": "0.2.8", "openunmix": "1.3.0",
                     "einops": "0.8.2", "omegaconf": "2.4.0"}
STRUCTURE_RUNTIME = {"torch": "2.8.0", "torchaudio": "2.8.0", "transformers": "4.45.2",
                     "numpy": "1.24.3", "soundfile": "0.14.0"}


def require_runtime(expected: dict[str, str]) -> dict[str, str]:
    actual = {name: version(name) for name in expected}
    if platform.python_version_tuple()[:2] != ("3", "11") or actual != expected:
        raise ValueError(f"Fixed vocal recipe requires Python 3.11 and {expected}; got {actual}")
    return actual


def verify_weight(path: Path, expected: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"Fixed recipe checkpoint is absent or unsafe: {path.name}")
    with path.open("rb") as handle:
        digest = hashlib.file_digest(handle, "sha256").hexdigest()
    if digest != expected:
        raise ValueError(f"Fixed recipe checkpoint SHA mismatch: {path.name}")
    return digest


def verify_separator(repo: Path) -> str:
    config = repo / "htdemucs.yaml"
    if (config.is_symlink() or not config.is_file() or config.stat().st_size > 1024
            or config.read_text().strip() != "models: ['955717e8']"
            or {p.name for p in repo.glob("*.th")} != {DEMUCS_WEIGHT}):
        raise ValueError("Fixed recipe requires one exact htdemucs model bag and checkpoint")
    return verify_weight(repo / DEMUCS_WEIGHT, DEMUCS_SHA256)
