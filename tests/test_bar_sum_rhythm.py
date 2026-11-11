import itertools
import math
import unittest
from dataclasses import asdict, replace

from scripts.bar_sum_rhythm import (
    Clock,
    Observation,
    Solution,
    WrittenNote,
    accent_cost,
    candidates,
    notation_cost,
    pieces,
    rests,
    search_phases,
    solve,
    structural_check,
    token_cost,
)
from scripts.run_bar_sum_rhythm import (
    ARMS,
    aggregate,
    ambiguity_controls,
    authored_scores,
    fingerprint,
    notation_metrics,
    performance,
)


class MeterContracts(unittest.TestCase):
    def setUp(self):
        self.clock = Clock(4, 4, 120)
        self.obs = (Observation('a', 60, 0, .5), Observation('b', 62, .5, 1.0))

    def test_clock_units(self):
        self.assertEqual(self.clock.bar, 48)
        self.assertAlmostEqual(self.clock.bar * self.clock.tick_seconds, 2)
        self.assertAlmostEqual(Clock(3, 4, 120).bar * self.clock.tick_seconds, 1.5)
        c = Clock(6, 8, 60, 1.5)
        self.assertAlmostEqual(c.bar * c.tick_seconds, 2)
        self.assertNotEqual(c.tick_seconds, Clock(6, 8, 60, 1).tick_seconds)

    def test_unsupported_or_invalid_clock(self):
        for args in ((5, 4, 120), (4, 4, 0), (4, 4, math.nan), (4., 4, 120), (4, 4, 120, 0)):
            with self.subTest(args=args), self.assertRaises(ValueError):
                Clock(*args)

    def test_candidates_use_no_reference(self):
        c = candidates(self.obs[0], self.clock)
        self.assertTrue(c)
        self.assertTrue(all(n.id == 'a' and n.pitch == 60 and n.duration > 0 for n, _ in c))
        self.assertIn(WrittenNote('a', 60, 0, 12), [n for n, _ in c])

    def test_fixed_inputs_immutable(self):
        before = fingerprint([asdict(x) for x in self.obs])
        for mode in ('independent', 'joint_sum', 'joint_notation'):
            solve(self.obs, self.clock, 0, mode)
        self.assertEqual(before, fingerprint([asdict(x) for x in self.obs]))

    def test_invalid_observations(self):
        bad = ((self.obs[0], replace(self.obs[1], id='a')),
               (replace(self.obs[0], onset=-.1),), (replace(self.obs[0], offset=0),),
               (replace(self.obs[0], voice=1),), (replace(self.obs[0], pitch=128),),
               (replace(self.obs[0], onset=math.nan),), ())
        for observations in bad:
            with self.subTest(observations=observations), self.assertRaises(ValueError):
                solve(observations, self.clock, 0)

    def test_invalid_modes_and_phase(self):
        for phase, mode in ((-1, 'joint_sum'), (48, 'joint_sum'), (0, 'other')):
            with self.assertRaises(ValueError):
                solve(self.obs, self.clock, phase, mode)

    def test_exact_simple_notes(self):
        expected = (WrittenNote('a', 60, 0, 12), WrittenNote('b', 62, 12, 12))
        for mode in ('independent', 'joint_sum', 'joint_notation'):
            self.assertEqual(solve(self.obs, self.clock, 0, mode).notes, expected)

    def test_joint_no_new_overlap(self):
        obs = (Observation('a', 60, 0, .7), Observation('b', 60, .5, 1.0))
        s = solve(obs, self.clock, 0)
        self.assertLessEqual(s.notes[0].end, s.notes[1].start)
        self.assertEqual(len(s.notes), 2)

    def test_exact_dp_matches_bruteforce(self):
        obs = (Observation('a', 60, .02, .55), Observation('b', 62, .52, .94))
        for mode in ('joint_sum', 'joint_notation'):
            costs = []
            for (a, ca), (b, cb) in itertools.product(*(candidates(x, self.clock) for x in obs)):
                if a.end > b.start:
                    continue
                value = ca + cb
                if mode == 'joint_notation':
                    value += notation_cost(0, a.start, 6, 48, False)
                    value += notation_cost(a.start, a.end, 6, 48, True)
                    value += notation_cost(a.end, b.end, 6, 48, False) if False else 0
                    value += notation_cost(a.end, b.start, 6, 48, False)
                    value += notation_cost(b.start, b.end, 6, 48, True)
                costs.append(value)
            self.assertAlmostEqual(solve(obs, self.clock, 6, mode).cost, min(costs))

    def test_barline_tie_does_not_add_an_attack(self):
        note = WrittenNote('a', 60, 36, 24)
        self.assertEqual(pieces(note.start, note.end, 0, 48), ((36, 48), (48, 60)))
        result = structural_check(Solution(0, 0, (note,)), self.clock, (self.obs[0],))
        self.assertTrue(result['invariant'])
        self.assertEqual(result['barline_ties'], 1)
        self.assertTrue(result['bar_sums_exact'])

    def test_same_pitch_reattacks_remain_distinct(self):
        obs = (self.obs[0], replace(self.obs[1], pitch=60))
        self.assertEqual([n.id for n in solve(obs, self.clock, 0).notes], ['a', 'b'])

    def test_pickup_and_partial_end_not_padded(self):
        s = solve(self.obs, self.clock, 6)
        self.assertEqual(s.notes[-1].end, 24)
        status = structural_check(s, self.clock, self.obs)
        self.assertEqual(status['complete_bars'], 0)
        self.assertEqual(s.notes[0].start, 0)

    def test_leading_and_internal_rests(self):
        notes = (WrittenNote('a', 60, 24, 12), WrittenNote('b', 62, 48, 12))
        self.assertEqual(rests(notes), ((0, 24), (36, 48)))
        status = structural_check(Solution(0, 0, notes), self.clock, self.obs)
        self.assertEqual(status['complete_bars'], 1)
        self.assertTrue(status['bar_sums_exact'])

    def test_overlap_is_not_a_successful_bar_sum(self):
        notes = (WrittenNote('a', 60, 0, 24), WrittenNote('b', 62, 12, 48))
        self.assertFalse(structural_check(Solution(0, 0, notes), self.clock, self.obs)['bar_sums_exact'])

    def test_fine_fragments_and_zero_rests(self):
        self.assertEqual(token_cost(0), 0)
        self.assertTrue(math.isfinite(token_cost(5)))
        self.assertEqual(pieces(3, 3, 0, 48), ())
        with self.assertRaises(ValueError):
            token_cost(-1)

    def test_equal_sum_does_not_identify_phase(self):
        control = ambiguity_controls()
        self.assertEqual(control['sum_only_equal_cost_phases'], 48)
        self.assertIsNone(control['notation_prior_selected_phase'])
        self.assertGreaterEqual(len(control['notation_prior_candidate_phases']), 4)
        self.assertTrue(control['same_sound_distinct_notation']['inputs_identical'])

    def test_flat_accent_is_not_hidden_downbeat(self):
        accents = tuple((i * 12, .4) for i in range(12))
        self.assertTrue(all(accent_cost(accents, p, 48) == 0 for p in range(48)))

    def test_accent_uses_observations_not_phase_label(self):
        accents = ((0, 1.), (12, .25), (24, .25), (36, .25), (48, 1.))
        self.assertLess(accent_cost(accents, 0, 48), accent_cost(accents, 12, 48))
        with self.assertRaises(ValueError):
            accent_cost(((0, math.nan),), 0, 48)

    def test_unknown_phase_has_no_reference_argument(self):
        import inspect
        self.assertEqual(tuple(inspect.signature(search_phases).parameters), ('observations', 'clock', 'accents'))

    def test_authored_corpus_size_and_reproducibility(self):
        scores = authored_scores()
        self.assertEqual(len(scores), 12)
        self.assertEqual(len({s['name'] for s in scores}), 12)
        self.assertEqual(performance(scores[0], 'jitter'), performance(scores[0], 'jitter'))
        for score in scores:
            obs, _, _ = performance(score, 'clean')
            self.assertEqual(len(obs), len(score['notes']))
            self.assertEqual(notation_metrics(score['notes'], score['notes'])['note_pair_exact'], 1)

    def test_missing_failed_rows_cannot_emit_summary(self):
        self.assertIsNone(aggregate([], ['a']))
        self.assertIsNone(aggregate([{'id': 'a', 'status': 'failed'}], ['a']))
        self.assertIsNone(aggregate([{'id': 'a', 'status': 'scored', 'arms': {}}], ['a']))
        self.assertEqual(len(ARMS), 5)


if __name__ == '__main__':
    unittest.main()
