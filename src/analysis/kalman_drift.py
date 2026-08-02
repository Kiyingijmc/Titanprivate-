"""KalmanDrift: 2-state Kalman filter (level, velocity) on log-price with a
Wald SPRT decision layer and an NIS (chi-square) integrity monitor.

Blueprint: docs/research/2026-07-12-novel-arsenal-brainstorm.md sections 1
and 14.2. Two SPRT modes (sprt_on):

  "velocity" (v1, default): the SPRT runs on the filter's standardized
    velocity z = v_hat / sqrt(P_vel). z is autocorrelated across bars, so
    alpha/beta are NOMINAL only -- the 2026-07-14 gate measured 27.1%
    realized false-entry vs the 5% design and NO-GO'd this mode. Kept
    bit-identical for reproducibility of that result. (Its original
    justification -- that an innovation-SPRT would fight the NIS monitor on
    drift transients -- is void: suspension needs nis_persist consecutive
    out-of-band bars, which a transient never produces. See
    docs/research/2026-08-01-gyroscope-audit.md F1/F2.)
  "innovation" (v2): the SPRT runs on the signed standardized one-step
    innovation u = eps/sqrt(S), which is approximately white when NIS~=1
    (the filter's own calibration target), so the Wald alpha/beta are
    approximately real. Drift is detected at ONSET and the SPRT self-quiets
    once the filter absorbs the new velocity -- episodic by construction.
    A crossing must additionally agree with the filter's trend estimate by
    z_confirm sigma (disagreement spends the evidence). Pre-registration:
    docs/research/2026-08-01-gyroscope2-gate.md.

Pure deterministic stdlib math -- no I/O, no wall-clock, no randomness, no
numpy. One instance per symbol, fed exactly once per closed H1 bar via
update(log_close, atr); the SPRT statistic accumulates across bars, which is
why this object is stateful rather than recompute-per-window.

Noise adaptation (asset-agnostic, no per-symbol constants):
  R (measurement) = 0.5 * rolling variance of 1-bar log returns * r_frac.
    The 0.5 is structural: a 1-bar return is a difference of two noisy
    observations, so its variance is ~2x the observation-noise variance the
    filter's R actually needs. This correction brings NIS to ~0.85 on clean
    noise (vs ~0.44 without it), making the chi-square band meaningful.
  Q (process) = constant-velocity discretization scaled by
    (q_atr_frac * ATR/price)^2.
Integrity: rolling mean of NIS = eps^2/S over nis_window bars must sit in
1 +/- nis_z*sqrt(2/W). Suspension is a RARE failsafe: it triggers only after
the mean stays out of band for a full window of consecutive bars (a drift
onset is a brief spike and never trips it; a sustained regime break does).
While suspended the SPRT emits no decision and both Lambda statistics FREEZE
at their pre-suspension values (accumulated evidence is retained, not
discarded); accumulation resumes the bar the mean returns to band.
"""
from collections import deque
from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Reading:
    level: float          # filtered log-price
    velocity: float       # filtered drift per bar (log units)
    z: float              # standardized velocity v_hat / sqrt(P_vel) -- SPRT input
    S: float              # innovation variance (log units^2)
    sqrt_S_price: float   # 1-sigma price-space uncertainty at this level (for stops)
    nis: float            # this bar's eps^2/S
    nis_mean: float       # rolling NIS mean (1.0 until the window fills)
    lam_long: float       # SPRT statistic, long test
    lam_short: float      # SPRT statistic, short test
    crossed: str          # "LONG" | "SHORT" | "" (no boundary crossing)
    state: str            # "WARMUP" | "OBSERVE" | "SUSPENDED"
    u: float = 0.0        # signed standardized innovation eps/sqrt(S) (v2 SPRT input)


def _variance(values) -> float:
    n = len(values)
    if n < 2:
        return 0.0
    mean = sum(values) / n
    return sum((v - mean) ** 2 for v in values) / (n - 1)


class KalmanDrift:
    # Structural return-variance -> observation-noise correction (see module docstring).
    _R_RETURN_FACTOR = 0.5

    def __init__(self, warmup_bars=200, q_atr_frac=0.05, r_frac=1.0,
                 alpha=0.05, beta=0.20, delta=0.40, nis_window=50,
                 nis_z=2.576, sprt_on="velocity", z_confirm=0.0,
                 nis_persist=None):
        if sprt_on not in ("velocity", "innovation"):
            raise ValueError(f"sprt_on must be 'velocity' or 'innovation', got {sprt_on!r}")
        self.sprt_on = sprt_on
        self.z_confirm = float(z_confirm)
        self.warmup_bars = int(warmup_bars)
        self.q_atr_frac = float(q_atr_frac)
        self.r_frac = float(r_frac)
        self.delta = float(delta)
        self.nis_window = int(nis_window)
        # Suspension requires nis_persist consecutive out-of-band bars.
        # Default (v1) is a full window -- a rare failsafe never tripped by a
        # brief drift-onset spike; v2 sets a smaller value so the brake is
        # reachable on a genuine sustained regime break (audit F7).
        self.nis_persist = self.nis_window if nis_persist is None else int(nis_persist)
        self.A = math.log((1.0 - float(beta)) / float(alpha))
        self.B = math.log(float(beta) / (1.0 - float(alpha)))
        band = float(nis_z) * math.sqrt(2.0 / self.nis_window)
        self.nis_lo = 1.0 - band
        self.nis_hi = 1.0 + band

        self.n = 0
        self.x = None                 # [level, velocity]
        self.P = None                 # 2x2 covariance (list of lists)
        self.lam_long = 0.0
        self.lam_short = 0.0
        self.suspended = False
        self._oob = 0                 # consecutive out-of-band NIS-mean bars
        self._rets = deque(maxlen=self.nis_window)
        self._nis = deque(maxlen=self.nis_window)
        self._prev_y = None

    def update(self, log_close, atr) -> Reading:
        y = float(log_close)
        self.n += 1

        if self.x is None:
            self.x = [y, 0.0]
            self.P = [[1e-4, 0.0], [0.0, 1e-8]]
            self._prev_y = y
            return Reading(level=y, velocity=0.0, z=0.0, S=1e-4,
                           sqrt_S_price=math.sqrt(1e-4) * math.exp(y),
                           nis=0.0, nis_mean=1.0, lam_long=0.0,
                           lam_short=0.0, crossed="", state="WARMUP")

        self._rets.append(y - self._prev_y)
        self._prev_y = y

        R = max(self._R_RETURN_FACTOR * _variance(self._rets) * self.r_frac, 1e-12)
        price = math.exp(self.x[0])
        atr_log = (float(atr) / price) if price > 0 else 0.0
        q = (self.q_atr_frac * atr_log) ** 2
        # constant-velocity process noise, dt=1: q * [[1/3, 1/2], [1/2, 1]]

        # Predict: F = [[1, 1], [0, 1]]
        x0 = self.x[0] + self.x[1]
        x1 = self.x[1]
        p00 = self.P[0][0] + self.P[1][0] + self.P[0][1] + self.P[1][1] + q / 3.0
        p01 = self.P[0][1] + self.P[1][1] + q / 2.0
        p10 = self.P[1][0] + self.P[1][1] + q / 2.0
        p11 = self.P[1][1] + q

        # Innovate: H = [1, 0]
        eps = y - x0
        S = p00 + R

        # Update
        k0 = p00 / S
        k1 = p10 / S
        x0 += k0 * eps
        x1 += k1 * eps
        self.x = [x0, x1]
        p_vel = p11 - k1 * p01
        self.P = [[(1.0 - k0) * p00, (1.0 - k0) * p01],
                  [p10 - k1 * p00, p_vel]]

        nis = (eps * eps) / S if S > 0 else 0.0
        self._nis.append(nis)
        window_full = len(self._nis) == self.nis_window
        nis_mean = (sum(self._nis) / len(self._nis)) if window_full else 1.0

        # Integrity monitor: sustained out-of-band => SUSPENDED (checked
        # BEFORE the SPRT so an invalid model never produces a decision).
        if window_full and not (self.nis_lo <= nis_mean <= self.nis_hi):
            self._oob += 1
        else:
            self._oob = 0
        self.suspended = self._oob >= self.nis_persist

        warmed = self.n >= self.warmup_bars
        p_vel_pos = self.P[1][1] if self.P[1][1] > 0 else 1e-18
        z = x1 / math.sqrt(p_vel_pos)
        u = eps / math.sqrt(S) if S > 0 else 0.0
        crossed = ""
        if warmed and not self.suspended:
            d = self.delta
            # v1 tests the (autocorrelated) velocity statistic; v2 tests the
            # ~white standardized innovation, so drift is detected at ONSET and
            # the SPRT self-quiets once the filter absorbs the new velocity.
            s = z if self.sprt_on == "velocity" else u
            self.lam_long += d * s - 0.5 * d * d
            self.lam_short += -d * s - 0.5 * d * d
            if self.lam_long <= self.B:
                self.lam_long = 0.0
            if self.lam_short <= self.B:
                self.lam_short = 0.0
            if self.lam_long >= self.A:
                crossed = "LONG"
            elif self.lam_short >= self.A:
                crossed = "SHORT"
            if crossed and self.sprt_on == "innovation":
                # crossing must agree with the filter's own trend estimate by
                # at least z_confirm sigma; a disagreeing crossing still spends
                # its accumulated evidence (both lambdas reset below).
                if crossed == "LONG" and z < self.z_confirm:
                    crossed = ""
                    self.lam_long = self.lam_short = 0.0
                elif crossed == "SHORT" and z > -self.z_confirm:
                    crossed = ""
                    self.lam_long = self.lam_short = 0.0
            if crossed:
                self.lam_long = 0.0
                self.lam_short = 0.0

        state = "SUSPENDED" if self.suspended else ("OBSERVE" if warmed else "WARMUP")
        return Reading(level=x0, velocity=x1, z=z, S=S,
                       sqrt_S_price=math.sqrt(S) * math.exp(x0),
                       nis=nis, nis_mean=nis_mean,
                       lam_long=self.lam_long, lam_short=self.lam_short,
                       crossed=crossed, state=state, u=u)
