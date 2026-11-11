"""Drum beat/meter inference contract tests, no dataset-dependent tuning."""
from __future__ import annotations

import io
import zipfile

import mido
import pytest

from scripts.drum_meter_probe import (
    BACKBEAT,
    Hit,
    conflict,
    infer,
    metadata_candidate,
    parse_midi,
)
from scripts.run_drum_meter_probe import (
    aggregate,
    candidates_from_manifest,
    manifest,
    matches_bpm,
    safe_member,
    tempo_alias,
)


def rendered_hits(meter, bpm=120, bars=12, *, backbeat='snare', ambiguous=False):
    events = []
    for beat in range(meter * bars):
        part = beat % meter
        if part == 0 or (meter == 4 and part == 2):
            events.append(Hit(beat * 60. / bpm, 'kick', 1. if part == 0 else .65))
        if part in ((1, 3) if meter == 4 else (1, 2)):
            # Rim, clap and snap are mapped into the same role in this event-level study.
            events.append(Hit(beat * 60. / bpm, 'backbeat', .8))
    return tuple(sorted(events, key=lambda v: v.time))


@pytest.mark.parametrize('meter', (3, 4))
def test_waltz_and_four_four_tempo_meter_detected(meter):
    result = infer(rendered_hits(meter))
    assert result['status'] == 'scored'
    assert result['bpm'] == 120
    assert result['meter'] == meter


def test_symmetrical_rock_backbeat_has_ambiguous_downbeat():
    x = infer(rendered_hits(4), bpm=120, meter=4)
    assert x['phase'] is None
    assert x['phase_margin'] == pytest.approx(0, abs=1e-10)


def test_three_four_has_unique_downbeat_when_pattern_informative():
    x = infer(rendered_hits(3), bpm=120, meter=3)
    assert x['phase'] == 0


def test_no_kick_does_not_fake_complete_meter_result():
    h = tuple(Hit(i * .5, 'backbeat') for i in range(12))
    assert infer(h)['status'] == 'insufficient_drum_roles'


def test_offbeat_source_does_not_become_metadata_proof():
    h = rendered_hits(4)
    candidate = infer(h)
    external = metadata_candidate({'recording_id': 'same', 'bpm': 120,
                                    'time_signature': '3/4'}, 'same')
    assert conflict(candidate, external) == 'conflicting_candidates'


def test_metadata_is_version_bound_and_a_tempo_prior_not_silent_truth():
    data = {'recording_id': 'live', 'bpm': 120, 'time_signature': '4/4'}
    assert metadata_candidate(data, 'studio')['status'] == 'unverified_recording'
    assert metadata_candidate(data, 'studio')['bpm'] is None
    assert metadata_candidate(data, 'live')['status'] == 'matched'
    assert metadata_candidate({**data, 'time_signature': '6/8'}, 'live')['meter'] is None
    assert metadata_candidate({**data, 'bpm': 0}, 'live')['status'] == 'invalid_bpm'
    assert metadata_candidate({**data, 'bpm': float('nan')}, 'live')['status'] == 'invalid_bpm'


def test_half_double_tempo_is_reported_not_silently_normalized():
    assert tempo_alias(60, 120) == 'half_double'
    assert tempo_alias(240, 120) == 'half_double'
    assert not matches_bpm(60, 120)


def test_reject_invalid_inference_input():
    with pytest.raises(ValueError):
        infer((Hit(.5, 'kick'), Hit(.2, 'backbeat')))
    with pytest.raises(ValueError):
        infer(rendered_hits(3), meter=6)


def test_gmd_roland_snare_rim_clap_ids():
    assert {37, 38, 39, 40}.issubset(BACKBEAT)
    assert 42 not in BACKBEAT
    # Snap has no canonical dedicated GM identifier: needs acoustic validation.


def test_midi_parser_preserves_drum_role_and_timing():
    mf = mido.MidiFile(ticks_per_beat=480)
    t = mido.MidiTrack()
    mf.tracks.append(t)
    t.append(mido.MetaMessage('set_tempo', tempo=500000, time=0))
    t.append(mido.MetaMessage('time_signature', numerator=4, denominator=4, time=0))
    t.append(mido.Message('note_on', channel=9, note=36, velocity=100, time=0))
    t.append(mido.Message('note_on', channel=9, note=37, velocity=100, time=480))
    t.append(mido.Message('note_on', channel=9, note=39, velocity=100, time=480))
    buf = io.BytesIO()
    mf.save(file=buf)
    hits, meter, tempos = parse_midi(buf.getvalue())
    assert len(hits) == 3
    assert [x.role for x in hits] == ['kick', 'backbeat', 'backbeat']
    assert [x.time for x in hits] == [0, .5, 1.0]
    assert meter[0][1:] == (4, 4)
    assert len(tempos) == 1


def test_archive_manifest_and_unsafe_name_boundary():
    b = io.BytesIO()
    with zipfile.ZipFile(b, 'w') as z:
        z.writestr('groove/info.csv', 'id,split,beat_type,bpm,time_signature,midi_filename\n'
                    'example,test,beat,120,4-4,a.mid\n')
    b.seek(0)
    with zipfile.ZipFile(b) as z:
        prefix, rows = manifest(z)
        assert prefix == 'groove/'
        assert len(rows) == 1
        selected, counts = candidates_from_manifest(rows)
        assert selected[0]['id'] == 'example'
        assert counts['4-4'] == 1
        with pytest.raises(ValueError):
            safe_member(z, '../groove/info.csv')


def test_complete_aggregator_rejects_missing_and_duplicates():
    assert aggregate([], ['a']) is None
    assert aggregate([{'id': 'a'}], ['a', 'b']) is None
    assert aggregate([{'id': 'a'}, {'id': 'a'}], ['a', 'b']) is None


def test_no_wrong_automatic_meter_choice_for_three_four_under_bpm_metadata():
    a = infer(rendered_hits(3, bpm=96), bpm=96)
    assert a['meter'] in (None, 3)
