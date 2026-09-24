# Scoped Re-Review: Confidence–Skew Screen — Task 6 fix (delete unsound permutation null)

**Plan:** `.superpowers/sdd/2026-08-04-confidence-skew-screen/`
**Diff reviewed:** `review-058814c..bf1cf44.diff` — single commit `bf1cf44` (`fix(screen): delete unsound permutation null, invert bootstrap for p-value`)
**Files touched (confirmed via `git diff --name-only 058814c bf1cf44`):** `scripts/confidence_screen/inference.py`, `tests/unit/test_confidence_screen_inference.py` — exactly the two expected files, 0 files under `src/`.

## CRITICAL finding — "permutation null fragments unequal clusters, 15% FPR against 5% nominal"

**ADDRESSED.**

- `grep -n "remap\|straight\|shuffled\|\bnull\b" scripts/confidence_screen/inference.py` returns exactly one hit, and it's prose in the `cluster_bootstrap` docstring describing that the permutation null "existed here until 2026-08-04 and has been deleted, not disabled." No `remap`/`straight`/`shuffled` identifiers remain anywhere, in code or comments. No commented-out code, no feature flag.
- The surviving loop only builds `boot[d] = spearman_rho(x[idx], y[idx])` with a single `idx` applied to both arrays — no fragmentation path exists to reintroduce.
- The p-value now comes from `pvalue = float(min(1.0, 2.0 * min((boot <= 0.0).mean(), (boot >= 0.0).mean())))`, i.e. inverting the one resampling distribution, exactly as the amended spec §4.1 mandates: `p = 2 · min(P(ρ* ≤ 0), P(ρ* ≥ 0))`, clipped to 1.

## IMPORTANT finding — "equal 10-per-cluster fixtures hid the defect from all 14 tests"

**ADDRESSED.**

Confirmed via diff: `TestClusterBootstrap._data` and the fixture inside `test_pure_noise_is_not_significant` were both converted from `np.repeat(np.arange(n // 10), 10)` (equal blocks) to the new `_ragged_clusters(rng, n_clusters, lo=3, hi=41)` helper (sizes drawn uniformly from [3, 41)) — not just the two new calibration tests. This is the fixture class the CRITICAL finding says was blind to the bug, and it's now genuinely ragged.

## Requirement-by-requirement verification

### 1. `remap`/`straight`/`null` gone — deleted, not disabled

**ADDRESSED**, evidence above.

### 2. p-value formula matches spec exactly, clip to 1.0, sane at extremes

**ADDRESSED.** Ran the shipped function directly against three extremes (not trusting the report's prose):

```
strong assoc (rho≈0.9999, all boot draws same side): pvalue=0.0, ci=[0.9999, 0.99998]
degenerate y=const (spearman_rho always exactly 0.0, both P(<=0) and P(>=0) = 1.0):
    pre-clip value = 2.0, clipped result: pvalue=1.0  ← clip verified live
pure noise (rho≈-0.087): pvalue=0.04 — plausible false-alarm-rate behavior
```

The clip is exercised (not dead code) by the degenerate-y case, and every extreme behaves sanely: a real strong effect floors at p=0 (all mass on one side of zero), a genuinely null relationship saturates at the clip, and noise lands in a plausible range. Formula text-matches spec §4.1's `p = 2 · min(P(ρ* ≤ 0), P(ρ* ≥ 0))`, clipped to 1, character for character in intent (`<=`/`>=` both include 0, matching the spec's `≤`/`≥`).

Worth noting, not a defect: a p-value of exactly 0.0 for a very strong effect is an inherent property of this percentile-inversion method at finite `n_draws` (no draw crosses zero), not something the implementer introduced — it follows mechanically from the owner-ratified formula.

### 3. THE CALIBRATION TEST — assessed honestly, with independent verification

**Is the test capable of failing for a meaningfully miscalibrated method?** Only for a *gross* violation, not a *moderate* one. The 3-SE band `[0.86%, 9.14%]` at N_TRIALS=250 is wide by construction — the implementer's own reasoning is correct that it would resoundingly catch the deleted method's actual 15% (>7 SE outside), but a method whose true FPR sits anywhere in the high single digits (say 8–9%) would pass this test the large majority of the time. **Classify this test as a regression guard against the specific deleted defect, not a precision instrument capable of certifying "this method is nominal."** That distinction is not stated in the implementer's report, which characterizes the 7.6% result as unambiguously "consistent with nominal" — true, but the test's power to distinguish "nominal" from "mildly anti-conservative" is genuinely weak, and that should be said plainly rather than implied only by the SE arithmetic.

**Is 7.6% vs 5.0% noise, or a real anti-conservative signal?** I ran two independent calibration passes against the actual shipped `cluster_bootstrap`, not reusing the implementer's code or seeds, to get a second opinion:

| Run | Config | Trials | FPR | z vs nominal |
|---|---|---|---|---|
| Implementer, run 1 (in test suite) | 15 clusters, 300 draws | 250 | 7.6% (19/250) | 1.89 |
| Implementer, run 2 (standalone) | 15 clusters, 300 draws | 300 | 6.33% | — |
| Implementer, run 3 (standalone) | 10 clusters, 1000 draws | 40 | 7.5% | — |
| **Mine, matching shipped config** | **15 clusters, 300 draws, seed=13579** | **220** | **5.91% (13/220)** | **0.62** |
| Mine, harsher config | 12 clusters, 200 draws, seed=999888777 | 400 | **10.0% (40/400)** | **4.59** |

My run at the *exact* configuration the shipped test uses (15 clusters, 300 draws) landed at 5.91% — comfortably inside the band, on the low side of the implementer's own three measurements (6.33%–7.6%). Pooling all four independent 15-cluster measurements (mine + implementer's three), the central tendency sits around **6.5–7%**, mildly above the 5% nominal but not dramatically so, and every single one is far from the deleted method's 15%.

My second run, deliberately using *fewer* clusters (12 instead of 15) with a different seed, measured a clearly elevated **10.0% FPR (z=4.59, p≪0.0001 against nominal)**. This is not evidence the fix is broken — it reproduces a well-documented, generic property of cluster-bootstrap inference: **few-cluster over-rejection** (the number of independent resampling units, not `n_draws`, drives the finite-sample bias; this affects essentially any legitimate cluster-robust method, including the correct sound one shipped here, and is a separate phenomenon from the *fragmentation* mechanism that made the deleted permutation null unsound). Two things bound the practical risk: (a) the shipped calibration test's own choice of 15 clusters is already stricter than production, which resamples ~157 calendar-week blocks — an order of magnitude more resampling units, where this bias should shrink substantially; (b) the magnitude at 15 clusters (mid-single-digit percentage points above nominal) is categorically different from the deleted defect's 3x inflation.

**My view:** the 6–8% central tendency at the test's own 15-cluster configuration is *plausibly* a mix of ordinary sampling noise and a small, genuine anti-conservative bias consistent with the known finite-sample behavior of percentile/reflection-style bootstrap p-values combined with a modest cluster count — not evidence of the same class of defect that was just removed. I would not block this fix on it, because (1) the exact formula was explicitly ratified by the owner in the spec amendment — my job here is to verify compliance with that ruling, not re-litigate it; (2) production's ~157-block regime is far more favorable than the 15-cluster test regime; (3) the deviation is an order of magnitude smaller than what was just fixed. But I'd flag it as a documented residual limitation, not close the book on "calibration proven" — the report's framing ("No miscalibration was found") overstates what a 250-trial, 15-cluster check can actually certify. A tighter/larger-N recalibration, or a note in the results doc that p-values from this method carry a small conservative haircut, would be a reasonable follow-up but is not a blocking gap for this task.

### 4. Companion power test genuinely detects a real association

**ADDRESSED.** Ran standalone: `test_still_detects_genuine_association_with_ragged_clusters` — `Ran 1 test in 1.820s — OK`. Confirmed by reading the assertions (`rho > 0.3`, `pvalue < 0.05` on `y = 0.6*x + noise`) that a method stuck at `pvalue=1.0` could not pass it.

### 5. Existing `TestClusterBootstrap` fixtures actually changed to unequal sizes

**ADDRESSED** — see IMPORTANT finding above.

### 6. `_midrank` vectorization — behavior-preserving

**ADDRESSED**, verified independently rather than trusting the "200 randomized trials" claim in the report. I reimplemented the old element-loop version from the pre-fix source and diffed it against the shipped `_midrank` over 300 of my own randomized trials (sizes 0–50, mixes of no-ties/heavy-ties/already-sorted/reverse-sorted) plus explicit edge cases:

- Empty array, single element, all-tied (n=5), strictly ascending, strictly descending — all bit-identical.
- Single NaN and **multiple NaNs** (not mentioned in the report) — both old and new give `[1. 3. 4. 2. 5.]` for `[1.0, nan, nan, 2.0, nan]`, because both implementations group ties via `!=` comparison and `NaN != NaN` is always `True` in numpy, so NaNs never accidentally get treated as a tie group in either version. Identical behavior, including this edge case.
- 0/300 mismatches across the randomized sweep.

This is a genuinely behavior-preserving vectorization, including for the reachable-NaN case the report didn't explicitly test.

### 7. Only `inference.py` and its test module changed

**ADDRESSED.** `git diff --name-only 058814c bf1cf44` → exactly `scripts/confidence_screen/inference.py` and `tests/unit/test_confidence_screen_inference.py`. Zero files under `src/`.

## Full module run (not trusting the report's number)

```
.venv/bin/python -m unittest tests.unit.test_confidence_screen_inference -v
Ran 16 tests in 128.470s
OK
```

16/16 pass (matches the report's claimed 16, timing 128.5s vs their reported 120.8s — normal run-to-run variance, both comfortably under the module's documented ~budget).

## New breakage introduced by this diff

None found. No Critical or Important issues in the fix diff itself. The one thing I'd want on record (not a blocker) is the calibration-test-power caveat in §3 above — the test is a sound regression guard against the specific deleted defect, but its accept band is too wide, and its cluster count too low relative to production, to certify the replacement method is exactly nominal; multiple independent reruns center a bit above 5% at the test's own configuration. That's a property of the owner-ratified method and the test's design budget, not something the implementer got wrong within the scope of this fix.

## Verdict

All 7 verification items ADDRESSED. The CRITICAL defect (fragmenting permutation null) and the IMPORTANT defect (equal-size fixtures blind to it) are both genuinely fixed — deletion confirmed by grep, not a flag; fixtures confirmed ragged by diff, not just new tests. The `_midrank` scope-creep is genuinely behavior-preserving under independent differential testing including an edge case (multi-NaN) the report didn't cover. Only `inference.py` and its test module changed. The calibration test's honest classification is "regression guard for the deleted defect," not "proof of nominal calibration" — the measured FPR sits mildly above nominal across every independent 15-cluster rerun (mine included), which is expected of this class of method at this cluster count and does not rise to a blocking concern, but the report's "no miscalibration found or concealed" framing is more confident than the evidence supports.

MIG-VERDICT: PASS
