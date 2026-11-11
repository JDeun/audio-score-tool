import math
from types import SimpleNamespace

import pytest

from scripts.symbolic_mono_likelihood import score_mono


class Codec:
    def get_inputs_batch(self, rows, full_length):
        assert full_length
        return rows

    def events_to_label(self, events, position):
        return events[position] + 2

    def evaluate_log_likelihood(self, rows, probabilities):
        return [sum(math.log(probabilities[i][t - 1][self.events_to_label(row, t)])
                    for t in range(1, len(row))) for i, row in enumerate(rows)]


def fake_model():
    class Graph:
        def get_collection(self, key):
            return {"inputs": ["input"], "softmax": ["output"],
                    "initial_state": ["h", "c"], "temperature": ["temperature"]}[key]

    class Session:
        graph = Graph()

        def run(self, tensor, feed_dict=None):
            if tensor == ["h", "c"]:
                return ["zero_h", "zero_c"]
            assert tensor == "output"
            assert feed_dict["h"] == "zero_h" and feed_dict["c"] == "zero_c"
            assert feed_dict["temperature"] == 1.0
            return [[[1.0 / 130] * 130 for _ in row] for row in feed_dict["input"]]

    return SimpleNamespace(_session=Session(), _batch_size=lambda: 3,
                           _config=SimpleNamespace(encoder_decoder=Codec()))


def test_pretrained_graph_boundary_without_pitch_or_time_changes():
    events = [0, -2, -1, 127, -2]
    before = events.copy()
    score, receipt = score_mono(fake_model(), events)
    assert score == pytest.approx(-4 * math.log(130))
    assert events == before
    assert receipt["steps_scored"] == 4 and receipt["batch_size"] == 3
    assert receipt["manual_logsum_parity"]


@pytest.mark.parametrize("events", [[], [60], [True, 60], [128, 60], [-3, 60], [60.0, 61]])
def test_invalid_symbolic_sequences_are_not_normalized(events):
    with pytest.raises(ValueError, match="Invalid"):
        score_mono(fake_model(), events)


def test_mismatched_upstream_score_is_not_accepted():
    model = fake_model()
    model._config.encoder_decoder.evaluate_log_likelihood = lambda *args: [0.0] * 3
    with pytest.raises(ValueError, match="parity"):
        score_mono(model, [60, -2, 61])


def test_oversized_restored_batch_is_rejected():
    model = fake_model()
    model._batch_size = lambda: 1024
    with pytest.raises(ValueError, match="batch size"):
        score_mono(model, [60, -2])
