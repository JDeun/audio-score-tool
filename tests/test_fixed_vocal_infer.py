"""Reject runtime/checkpoint substitution before importing the model runtime."""
import sys

import pytest

from audio_score_tool import fixed_lead_recipe
from audio_score_tool import fixed_vocal_infer as adapter


def test_wrong_runtime_is_rejected_before_checkpoint_or_model_access(tmp_path, monkeypatch):
    monkeypatch.setattr(sys, "argv", ["fixed-vocal", "vocal", "source.wav", str(tmp_path / "output.mid"),
                                    "--snapshot", str(tmp_path)])
    monkeypatch.setattr(fixed_lead_recipe, "version", lambda _: "wrong-version")
    monkeypatch.setattr(adapter, "verify_weight", lambda *a: pytest.fail("must reject runtime first"))
    with pytest.raises(ValueError, match="requires Python 3.11"):
        adapter.main()
    assert not (tmp_path / "output.mid").exists()
