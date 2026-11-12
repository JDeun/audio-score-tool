# Research PR integration and cleanup — 2026-11-12

This records a later repository-state snapshot than [RESEARCH_STATUS_2026-11-12.md](RESEARCH_STATUS_2026-11-12.md). The user explicitly requested continuing the experiments and merging ready work instead of accumulating open PRs. Under that instruction, #272 was merged after its required checks passed, and 14 older research review threads were closed after verifying that their complete current heads were already integrated. Research code inclusion remains separate from experimental product activation.

## Snapshot boundary and completed actions

The main commit for this snapshot is `1c9514e30e2aac92ba6857e67a940dc48b6a03e6`. [PR #272](https://github.com/JDeun/audio-score-tool/pull/272) reports `merged=true`, merged at **2026-11-12 08:19:15 UTC / 17:19:15 Asia/Seoul**, from head `4e0e1fbf96ae22c15f5a7758b00a0f577d7513b8`. [Issue #271](https://github.com/JDeun/audio-score-tool/issues/271) was closed at 08:20:26 UTC after completion.

The 14 legacy research PRs were closed between 08:19:57 and 08:20:22 UTC. Each retains its original description below an added integration-evidence section. Their GitHub state is **closed, merged=false**: they were closed as already integrated through [#266](https://github.com/JDeun/audio-score-tool/pull/266), without creating redundant merges or discarding their experiment records.

A subsequent open-PR read returned **only #236**. This count applies to the cleanup snapshot, before the separate KRAISLER follow-up PR. That experiment is being prepared separately and must record its own results and validation; neither its outcome nor its eventual merge is asserted here. The earlier 15/16-open-PR counts are historical snapshots, not contradictory current-state claims.

## #272 merge evidence and checks

The [required pre-merge CI 43180799642](https://github.com/JDeun/audio-score-tool/actions/runs/43180799642) completed successfully on head `4e0e1fbf96ae22c15f5a7758b00a0f577d7513b8`. Its actual checkout was PR test-merge commit `aea1f252f5b5add21a71e5e8775c280c4104812e`, combining that head with main `7dd5c6ce0b18fda023403d92fba981867a1f0202`.

- changes, Python, frontend and required `verify` succeeded. Tauri was conditionally skipped with `required=false`; it was not a newly executed Tauri pass.
- [Python job 131055991376](https://github.com/JDeun/audio-score-tool/actions/runs/43180799642/job/131055991376): **2,119 product tests passed, 9 optional skips; 631 research tests passed, 1 upstream warning**. Inventory: 200 product files, 30 research files, zero omitted files.
- [Research Evidence Contracts 43180799453](https://github.com/JDeun/audio-score-tool/actions/runs/43180799453) succeeded at the same head. [Research Integration Audit 43180799558](https://github.com/JDeun/audio-score-tool/actions/runs/43180799558) was conditionally skipped.

Post-merge checks run on the actual main merge `1c9514e30e2aac92ba6857e67a940dc48b6a03e6`, separately from that pre-merge evidence:

- [Main CI 43181970207](https://github.com/JDeun/audio-score-tool/actions/runs/43181970207): **completed / success**, finished at **08:24:44 UTC / 17:24:44 Asia/Seoul**. All five jobs, changes/Python/frontend/Tauri/required `verify`, executed successfully. [Python job 131059883675](https://github.com/JDeun/audio-score-tool/actions/runs/43181970207/job/131059883675) checked out the exact main merge and reported **2,119 product tests passed, 9 optional skips; 631 research tests passed, 1 upstream warning**. Both scopes accounted for 200 product and 30 research test files, with zero omitted files. The main-only stress run passed 57 checks on each of three passes; the soak passed two checks.
- [Dependency Security 43181970223](https://github.com/JDeun/audio-score-tool/actions/runs/43181970223): **completed / success** at the same main commit.

## Why the 14 legacy PRs could be closed

The [pinned integration manifest](https://github.com/JDeun/audio-score-tool/blob/7dd5c6ce0b18fda023403d92fba981867a1f0202/docs/research/RESEARCH_MERGE_MANIFEST_2026-11-12.json) identifies #265 head `ce32aa8d70ff495c9dc29d30dc0de9a504676bfe` and #244 head `838e0e6b7cf574e29c93348312702d1fd0013d29` as source stacks integrated by #266. The current legacy heads still matched the earlier audit; no newer branch commits had appeared.

For **every row below**, GitHub compare from that exact current head to main `7dd5c6ce0b18fda023403d92fba981867a1f0202` returned `status=ahead`, `behind_by=0`, and a merge-base equal to the PR head. Thus no PR-only commits remained. A separate [7dd5c6ce to 1c9514e3 comparison](https://github.com/JDeun/audio-score-tool/compare/7dd5c6ce0b18fda023403d92fba981867a1f0202...1c9514e30e2aac92ba6857e67a940dc48b6a03e6) returned ahead 4, behind 0, with merge-base `7dd5c6ce...`, preserving all 14 ancestry proofs in the new main. The added PR descriptions also record the integration ancestry against `1c9514e3...`.

| Closed PR | Verified final head | Integrated source stack |
|---|---|---|
| [#242](https://github.com/JDeun/audio-score-tool/pull/242) | `5e9c771da3f60fd01e318ed50e978a7d24e4c468` | #244 → #266 |
| [#243](https://github.com/JDeun/audio-score-tool/pull/243) | `ca50d68f8eb22cc60ca79e3c266b57204980055c` | #244 → #266 |
| [#251](https://github.com/JDeun/audio-score-tool/pull/251) | `6282321f9f58a49948e1167ae3d54865199c50cb` | #265 → #266 |
| [#253](https://github.com/JDeun/audio-score-tool/pull/253) | `94c085222c0becb86a59cc924f58075dce154e40` | #265 → #266 |
| [#254](https://github.com/JDeun/audio-score-tool/pull/254) | `d6fa009c203d1799c2329e802acf85b514c4bb70` | #265 → #266 |
| [#255](https://github.com/JDeun/audio-score-tool/pull/255) | `d953ad962463699c4647cc4923aa13094324cfbc` | #265 → #266 |
| [#256](https://github.com/JDeun/audio-score-tool/pull/256) | `fc307315d45cc3d3d6be6fca6c0255e58dece66e` | #265 → #266 |
| [#258](https://github.com/JDeun/audio-score-tool/pull/258) | `406b93ea59ba4cda53eadea37325822094c4ce94` | #265 → #266 |
| [#260](https://github.com/JDeun/audio-score-tool/pull/260) | `58ab50cf6be509e476913c7be460bdf43047c30f` | #265 → #266 |
| [#261](https://github.com/JDeun/audio-score-tool/pull/261) | `0dc3157f8bbc1fcb7307d53c80c73c52c00bcf39` | #265 → #266 |
| [#262](https://github.com/JDeun/audio-score-tool/pull/262) | `94aa494dc1badad843014767a2dfdc46eee32a60` | #265 → #266 |
| [#263](https://github.com/JDeun/audio-score-tool/pull/263) | `3c687aff0eadb23b645ce156fa1d764bc2c5a0ee` | #265 → #266 |
| [#264](https://github.com/JDeun/audio-score-tool/pull/264) | `f70581b72e037e44b156c1863fb8e8938e94341b` | #265 → #266 |
| [#265](https://github.com/JDeun/audio-score-tool/pull/265) | `ce32aa8d70ff495c9dc29d30dc0de9a504676bfe` | #265 → #266 |

Closed review threads do not convert negative results into positive results, validate automatic correction, or close the broader research questions. Historical protocols, result limits, run identities and source branches remain available.

## Why #236 remains open

[PR #236](https://github.com/JDeun/audio-score-tool/pull/236), head `97513f02397189bd5295f84586739a97b5b4dc96`, is a separate product Beat This DBN-clock change, explicitly excluded by #266's manifest. It is not an already-integrated research duplicate. Its [comparison against the pre-cleanup main](https://github.com/JDeun/audio-score-tool/compare/7dd5c6ce0b18fda023403d92fba981867a1f0202...97513f02397189bd5295f84586739a97b5b4dc96) was diverged: 11 PR-only commits, 182 main-only commits, and 17 PR-side changed files including seven product source files. These counts describe that pinned comparison, not a future main.

The remaining reasons are substantive:

- Musical outcomes are mixed. The recorded American Idiot comparison improves beat/downbeat F1, but its 50 ms melody F1 falls **0.432 → 0.247**; both clock candidates reach 0.778 at 100 ms. FANCY's result depends on the timing-reference projection, and some pulse identities remain ambiguous.
- Independent original-song timing, the absolute reliability of community synchronization markers, and minimum-edit acceptance remain unresolved in the PR's own record. A few excerpts and one complete fresh Job do not establish broad product quality.
- [Existing CI 42917159593](https://github.com/JDeun/audio-score-tool/actions/runs/42917159593) succeeded on `97513f0...`, but it does not verify integration with the subsequently changed main. The isolated runtime and supported constant-meter conditions still need to be respected.

The PR's `base.sha` value `3c6fe4345903bbd96d832a22bbf3f9cb67a65908` is the historical [#235 merge](https://github.com/JDeun/audio-score-tool/commit/3c6fe4345903bbd96d832a22bbf3f9cb67a65908) and the observed common ancestor, not the current main ref. It must not be mistaken for another newly merged commit.

#236 and its private-song working data were not changed, merged or closed by this cleanup. Merging ready research and removing duplicate review threads does not remove these separate product acceptance gates.
