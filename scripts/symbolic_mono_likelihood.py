"""Teacher-forced mono_rnn adapter; no weights, training or pitch normalization.

Use the restored graph and upstream codec directly, avoiding the upstream
convenience helper's partial-batch padding/state assembly. Validate the codec's
sequence likelihood against an independent sum of the fetched softmax entries.
"""
from __future__ import annotations

import copy
import math


def score_mono(model, sequence):
    """Score an already representable sequence; return value and parity receipt."""
    events = list(sequence)
    if len(events) < 2 or any(type(x) is not int or not -2 <= x <= 127 for x in events):
        raise ValueError("Invalid mono_rnn events")
    session = model._session
    graph = session.graph
    input_tensor = graph.get_collection("inputs")[0]
    softmax_tensor = graph.get_collection("softmax")[0]
    batch_size = int(model._batch_size())
    if not 1 <= batch_size <= 128:
        raise ValueError("Unsupported restored batch size")
    sequences = [copy.deepcopy(sequence) for _ in range(batch_size)]
    codec = model._config.encoder_decoder
    inputs = codec.get_inputs_batch([s[:-1] for s in sequences], full_length=True)
    state_tensors = graph.get_collection("initial_state")
    states = session.run(state_tensors)
    if len(state_tensors) != len(states):
        raise ValueError("Restored state arity mismatch")
    feed = {input_tensor: inputs, **dict(zip(state_tensors, states))}
    temperature = graph.get_collection("temperature")
    if temperature:
        feed[temperature[0]] = 1.0
    probabilities = session.run(softmax_tensor, feed_dict=feed)
    if len(probabilities) != batch_size:
        raise ValueError("Restored batch output mismatch")
    scores = list(codec.evaluate_log_likelihood(sequences, probabilities))
    if len(scores) != batch_size or len(probabilities[0]) != len(events) - 1:
        raise ValueError("Unexpected sequence likelihood shape")
    manual = 0.0
    for t in range(1, len(events)):
        label = codec.events_to_label(sequence, t)
        p = float(probabilities[0][t - 1][label])
        if not math.isfinite(p) or not 0 < p <= 1:
            raise ValueError("Invalid pretrained probability")
        manual += math.log(p)
    score = float(scores[0])
    if not math.isfinite(score) or not math.isclose(score, manual, rel_tol=1e-6, abs_tol=1e-5):
        raise ValueError("Upstream codec/manual likelihood parity failure")
    if any(not math.isclose(float(x), score, rel_tol=1e-6, abs_tol=1e-5) for x in scores):
        raise ValueError("Identical padded sequences disagree")
    if list(sequence) != events or any(list(s) != events for s in sequences):
        raise ValueError("Sequence changed during inference")
    return score, {"adapter": "restored_graph_full_batch_teacher_forcing_v1",
                   "batch_size": batch_size, "steps_scored": len(events) - 1,
                   "manual_logsum_parity": True, "duplicate_batch_parity": True,
                   "pitch_squashing": False, "checkpoint_changed": False}
