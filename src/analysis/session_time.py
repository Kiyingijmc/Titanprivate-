# Broker-time -> New York session mapping for the ICT video-rules study.
# Spec: docs/superpowers/specs/2026-08-03-ict-video-rules-design.md (A1).
#
# The SB rig carries NY_SHIFT = -7 with the comment "broker(GMT+3ish) -> NY
# approx; +/-1h DST wobble accepted". This module replaces that approximation
# with a shift derived from the data itself. Pure functions, no pandas, no I/O.
#
# WHY AN ANCHOR RATHER THAN A UTC OFFSET: FBS server time follows US DST, so
# the broker's UTC offset moves twice a year (GMT+2 winter, GMT+3 summer) while
# its offset to New York does not. Routing through UTC therefore needs a
# per-date offset and is wrong at the DST boundaries.
#
# WHY THE WEEKEND SEAM AND NOT THE DAILY ROLLOVER: the obvious anchor is the
# daily maintenance gap, but this data has none - EURUSD M5 hourly bar counts
# run 8577-9324 across all 24 hours. The weekly seam is unambiguous instead:
# the FX week opens Sunday 17:00 New York, and 159 of 160 weekends in this data
# open at the same broker hour.
#
# Measured: shift = +17, identical across 2023-2026. Note 17 == -7 (mod 24),
# so this CONFIRMS the rig's NY_SHIFT = -7 rather than correcting it.

# NY-time killzone buckets, end-exclusive, snapped to H1 bar opens.
# Canonical ICT quotes 08:30-11:00 and 13:30-16:00; H1 bars cannot represent
# half-hour boundaries, so these snap outward to the bar open. Stated in the
# results doc as an approximation, not hidden.
KILLZONES = {
    "London KZ": (2, 5),
    "NY AM": (8, 11),
    "NY PM": (13, 16),
}
OUTSIDE = "Outside"

_WEEK_OPEN_NY_HOUR = 17    # the FX week opens Sunday 17:00 New York
_MIN_MODAL_SHARE = 0.80    # the modal open hour must cover this many weeks


def infer_ny_shift(week_open_hours):
    """Whole hours to ADD to a broker-local hour to get the New York hour.

    `week_open_hours` is the broker-local hour of the first bar after each
    weekend gap. The modal value pins the week open, which is 17:00 New York.

    Raises ValueError when there are no seams, or when the modal hour covers
    under _MIN_MODAL_SHARE of weeks - an unstable anchor aborts the run instead
    of silently bucketing on a wrong mapping.
    """
    if not week_open_hours:
        raise ValueError("no weekend seams found - cannot anchor the shift")
    counts = {}
    for h in week_open_hours:
        counts[h] = counts.get(h, 0) + 1
    modal_hour = max(counts, key=lambda h: (counts[h], -h))
    share = counts[modal_hour] / len(week_open_hours)
    if share < _MIN_MODAL_SHARE:
        raise ValueError(
            f"week-open hour is not stable: {sorted(counts.items())} "
            f"(modal share {share:.0%} < {_MIN_MODAL_SHARE:.0%}) - aborting")
    return (_WEEK_OPEN_NY_HOUR - modal_hour) % 24


def ny_bucket(broker_hour, ny_shift):
    """Map a broker-local hour to its NY killzone bucket."""
    ny_hour = (broker_hour + ny_shift) % 24
    for name, (start, end) in KILLZONES.items():
        if start <= ny_hour < end:
            return name
    return OUTSIDE
