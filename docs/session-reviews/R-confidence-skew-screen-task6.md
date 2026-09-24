# Review: Confidence–Skew Screen — Task 6 (Inference core: rank normalization, Spearman, cluster bootstrap, BH, ICC)

**Plan:** `.superpowers/sdd/2026-08-04-confidence-skew-screen/`
**Diff reviewed:** `review-5e8cbd7..8e4de23.diff` (commit `8e4de23`)
**Files:** `scripts/confidence_screen/inference.py`, `tests/unit/test_confidence_screen_inference.py`

## Verification performed

- Confirmed via diff that the implementation and test file are a byte-for-byte transcription of the brief's Step-1/Step-3 code (matches the implementer's "No Deviations" claim).
- Confirmed only these two files changed (`git show --stat 8e4de23`) — nothing under `src/`, nothing from Tasks 1–4's files.
- Confirmed `BOOTSTRAP_DRAWS`/`Q_FDR`/`SEED` are imported from `scripts/confidence_screen/__init__.py`, not redefined; `grep scipy` on both files returns nothing — only `numpy` is imported.
- Did **not** re-run the full 167s test module. Instead ran targeted, cheap scripts against the actual installed `inference.py` to check the statistical claims directly (all below).
- **BH edge cases** (empty, singleton, ties, boundary-equal-to-threshold — none of which the shipped test file exercises): traced the algorithm by hand and confirmed live —
  `benjamini_hochberg([])` → `[]`; single p passing/failing its own threshold behaves correctly; `[0.02, 0.02, 0.5]` at q=0.1 correctly rejects both tied 0.02's; `[0.01, 0.1]` at q=0.2 (thresholds `[0.1, 0.2]`) correctly rejects both at the boundary. The general formula (no special-casing) handles all four cases correctly because the threshold is monotone increasing in rank `i` while tied p-values are constant, so `passing[-1]+1` always captures every tied instance. This is a genuine strength: **the known-answer fixture (`p_(5)=0.042` rescuing `p_(4)=0.041`) is a real, discriminating test** — a naive per-test-threshold implementation fails it, and the shipped `mask[order[: passing[-1] + 1]] = True` logic (max index, not a monothonic-prefix scan) is what makes it pass. Mask is correctly returned in input order (verified via the two order-sensitive fixtures in the diff).
- **ICC**: confirmed the `n_bar` (average cluster size) term is present and used in the denominator (`ms_between + (n_bar - 1) * ms_within`) — this is the standard one-way random-effects ANOVA ICC estimator and it does the right thing for unequal cluster sizes (Fisher/Searle's average-size approximation, standard practice absent the exact unbalanced-ANOVA formula). Confirmed empirically that it **can go negative**: an engineered within-cluster-alternating fixture produces `icc = -0.25`; the pure-noise fixture from the brief itself produces `icc = -0.053` (technically still satisfies `abs(icc) < 0.2`, but note the "near zero" test would also pass a slightly-negative true value — not a bug, just worth knowing the sign isn't pinned).
- **Cluster bootstrap — the highest-risk piece.** Read `cluster_bootstrap` line by line and then traced the exact index arithmetic for a 3-cluster, unequal-size (`3,2,5`) toy example:

  ```
  shuffled cluster order: [2 0 1]
  remap    (x source idx): [5 6 7 8 9 0 1 2 3 4]
  straight (y source idx): [0 1 2 3 4 5 6 7 8 9]
  pos 0: x from cluster 2, y from cluster 0
  pos 1: x from cluster 2, y from cluster 0
  pos 2: x from cluster 2, y from cluster 0
  pos 3: x from cluster 2, y from cluster 1
  pos 4: x from cluster 2, y from cluster 1
  pos 5: x from cluster 0, y from cluster 2
  ...
  ```

  Cluster 2 (5 members) gets **fragmented across two different y-clusters** (0 and 1) purely because of cumulative-offset arithmetic — `remap`'s block boundaries (ordered by the shuffled permutation's cumulative sizes) don't line up with `straight`'s block boundaries (ordered by natural/sorted cumulative sizes) whenever cluster sizes differ. This is not a "whole cluster's x-block swapped against a whole cluster's y-block" permutation once sizes are unequal — it's an uncontrolled, offset-dependent mixing that partially decouples from cluster identity.
- Ran a quick calibration check (reduced `n_draws`/`n_clusters` for tractability, not the full `BOOTSTRAP_DRAWS=10000`) simulating a **true null** (x, y independent, but each carries its own within-cluster-correlated noise — the realistic case this module exists to handle) under equal vs. unequal cluster sizes, 20 trials each, α=0.05:
  - Equal-size clusters (10 each): **5.0% false-positive rate** — correctly calibrated.
  - Unequal-size clusters (sizes 3–18): **15.0% false-positive rate** — 3× the nominal rate.

  20 trials is a small sample (binomial SE ≈ 4.9pp at true 5%, so 15% is ≈2 SE away — suggestive, not airtight on its own), but it's directionally consistent with, and mechanistically explained by, the index-fragmentation trace above. I'm confident in the mechanism; the calibration numbers corroborate it.
- Checked the CI half of the same function (`boot[d] = spearman_rho(x[idx], y[idx])`, same `idx` for both arrays) — this is a standard resample-clusters-with-replacement block bootstrap and is **not** affected by the unequal-size problem, since it never tries to cross-pair x from one cluster against y from another; it always keeps the original x–y pairing within whatever clusters get drawn. The CI construction is sound regardless of cluster-size balance.
- Checked `rank_within_symbol`'s singleton constant (`0.5`): traced that this is **not** an ad-hoc special case — the general mid-rank formula `(rank - 0.5) / n` already evaluates to `0.5` for `n=1` (`rank=1`), so the `if n > 1 else 0.5` branch is redundant but not a source of bias. A symbol with very few signals contributes values clustered near the pooled-correlation midpoint, which dilutes power for that symbol's contribution but does not introduce directional bias, because that is exactly what the general formula would produce anyway.
- Checked test-suite honesty: no test in `TestClusterBootstrap` uses anything other than exactly-equal 10-per-cluster sizes (`np.repeat(np.arange(n // 10), 10)`), so **the entire suite is structurally blind to the unequal-cluster-size defect** — a case the module's own docstring says it exists to handle ("calendar-week blocks," which will not all contain the same number of signals in real data). None of the other tests are tautological; the BH known-answer fixture, ICC identical-vs-noise fixtures, and Spearman monotone/inverse fixtures all compute a real number and threshold it meaningfully.

## A) SPEC COMPLIANCE — PASS

- All five function signatures match the brief exactly: `rank_within_symbol(values, symbols)`, `spearman_rho(x, y)`, `benjamini_hochberg(pvalues, q=Q_FDR)`, `cluster_bootstrap(x, y, clusters, n_draws=BOOTSTRAP_DRAWS, seed=SEED) -> dict{rho, pvalue, ci_lo, ci_hi}`, `icc(values, clusters)`.
- `BOOTSTRAP_DRAWS`, `Q_FDR`, `SEED` imported from `scripts/confidence_screen/__init__.py`, not redefined.
- No scipy import; numpy/pandas only.
- Nothing under `src/` touched; no earlier-task file touched.
- stdlib `unittest` only (plus `numpy.testing`, which is part of the already-approved numpy dependency).
- Implementer's report claims ("transcribed exactly," "no deviations," "14 tests pass") check out against the diff.

## B) TASK QUALITY — Not approved

### Critical — the cluster-bootstrap null is statistically invalid for unequal cluster sizes, which is the realistic case this module exists to handle

`cluster_bootstrap`'s p-value comes from permuting cluster *order* for `x` (`remap`) while holding `y` in natural cluster order (`straight`), then computing `spearman_rho(x[remap], y[straight])`. When every cluster has the same size, this is a clean block-level permutation (verified: block boundaries in `remap` and `straight` coincide, so it's genuinely "cluster c's x-block vs. cluster c′'s y-block"). When cluster sizes differ — which calendar-week blocks of trading signals will, as a matter of course (holidays, session gaps, uneven signal density) — the block boundaries in `remap` (ordered by the *shuffled* permutation's cumulative sizes) and `straight` (ordered by the *natural* cumulative sizes) no longer align. A single x-cluster can straddle two or more unrelated y-clusters at essentially arbitrary offsets (demonstrated concretely above). This degrades the "preserve within-cluster dependence, permute across clusters" design the docstring claims into something closer to a finer-grained, offset-driven scramble — which under-corrects for clustering exactly the way the module's own opening comment warns against ("Naive p-values would assume ~2,200 independent observations against a far lower effective count... That is the standard way a panel study manufactures a false positive"). A quick calibration simulation (20 trials, reduced draws for tractability) showed a 15% false-positive rate at nominal α=5% under unequal cluster sizes, vs. 5.0% under equal sizes — consistent with the mechanism, though not a high-power confirmation given the trial count.

This is precisely the "subtly wrong p-value invisible in output" risk the review brief called out. It is inherited verbatim from the brief's own Step-3 reference code (same situation as the Task 3 plan-defect noted in `progress.md`), but unlike Task 3, the brief's own test fixtures never exercise the failing regime (all `TestClusterBootstrap` fixtures use exactly 10-per-cluster), so nothing forced it to surface. Recommend: build `remap`/`straight` so a cluster's x-block only ever gets compared against a *same-length* substitute (e.g., permute which cluster's *(x, y)-pair* occupies which position, rather than independently reordering x's cluster sequence against y's), or resample the null the same way `boot` is built (same-index pairing) but with a treatment/label permutation at the cluster level instead of order-based reindexing. Needs a fix and a test with genuinely unequal cluster sizes before this can be trusted on the real (unequal-size, calendar-week) dataset.

### Important — zero test coverage for unequal cluster sizes, so the Critical defect is invisible to the shipped suite

Every fixture in `TestClusterBootstrap` (`_data()` and the noise test) constructs clusters via `np.repeat(np.arange(n // 10), 10)` — exactly 10 members per cluster, always. A production run against real calendar weeks will not have this property. Recommend adding a fixture with deliberately uneven cluster sizes (e.g. `rng.integers(3, 20, size=k)`) and a calibration-style assertion (repeated draws under a true null, check the rejection rate is close to nominal) rather than a single-draw significance check — the current tests would pass unchanged even after the Critical fix above, or unchanged if the defect above is never fixed, because they don't discriminate between the two.

### Important — `icc()` is unclamped and can be negative; no documented contract for the downstream design-effect consumer

Confirmed empirically (`icc` on an engineered fixture returns `-0.25`) that the one-way ANOVA estimator is not bounded at zero, which is mathematically expected for this estimator but has a real consequence downstream: if a later task computes `DEFF = 1 + ICC * (n_bar - 1)` directly from this value without clamping, a sufficiently negative ICC drives `DEFF` below 1, implying an *effective* sample size larger than the actual sample — anti-conservative, i.e. it would make later inference look more precise than it is. No downstream consumer exists yet in this branch (checked — no `DEFF`/design-effect code anywhere in `scripts/confidence_screen/`), so this isn't a live bug today, but the function's docstring ("Feeds the design effect") doesn't state whether callers are expected to clamp, and nothing here does. Flag for whichever future task actually computes DEFF from this.

### Minor — BH edge cases (empty, singleton, ties, boundary-equal) are correct by inspection but untested

Manually verified all four behave correctly (see Verification section) — this is not a functional defect, since the general formula handles them without special-casing. But given the brief's own test file has no coverage for any of them, a future refactor of `benjamini_hochberg` could regress silently on exactly these cases. Cheap to add given they don't require bootstrap draws.

### No finding (explicitly checked, no issue)

- BH mask order (input order, not sorted) — correct, test-verified with two order-sensitive fixtures.
- BH known-answer fixture — genuinely discriminating (kills a naive per-test-threshold implementation).
- Spearman p-value sidedness — correctly two-sided (`abs(null) >= abs(observed)`).
- Cluster-bootstrap CI construction (`boot`) — sound resample-with-replacement block bootstrap, unaffected by the cluster-size issue above; mixing a bootstrap-resampling CI with a permutation-based p-value is a standard, coherent applied-stats pattern (not flagged as a defect on its own).
- `rank_within_symbol`'s singleton `0.5` — consistent with the general formula, not an ad-hoc bias source.

## Recommendation

Fix the Critical cluster-bootstrap null-construction defect and add an unequal-cluster-size calibration test before this module's p-values are used to draw any conclusion in the actual screen — this is the correctness-determining piece the task brief flagged up front, and as shipped it will under-correct for clustering (inflate false positives) on the real, unevenly-sized calendar-week data this whole module exists to handle correctly. The BH/ICC/rank-normalization/Spearman pieces are sound.

MIG-VERDICT: CHANGES
