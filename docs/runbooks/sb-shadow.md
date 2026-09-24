# SilverBullet prospective shadow recorder

This is an isolated, GET-only observer. It does not start the trading controller, place broker orders, or use `data/trade_state.db`. It compares the frozen wider-window midpoint and completed-session-range candidates on newly observed data.

## Start and view

From the repository root, with the usual `.env` bridge credentials available:

```bash
.venv/bin/python scripts/sb_shadow.py --directory data/shadow/sb_prospective_20260918 --port 8772
```

Dashboard: `http://127.0.0.1:8772`. It binds only to localhost. It reports source/quote health, frozen-cohort details, setup rejection reasons, hypothetical order states, and progress toward review. It provides CSV downloads of trades, decisions, quotes, completed bars and recorder events. There are no trading controls or write API endpoints.

For a single collection smoke check, use a **separate** directory:

```bash
.venv/bin/python scripts/sb_shadow.py --directory data/shadow/sb_smoke_20260918 --once
```

A smoke cohort remains separate from the prospective evaluation. Stopping a run marks pending/open hypothetical orders CENSORED; it does not fabricate exits. Ctrl-C or SIGTERM performs that shutdown. A crash leaves durable state; the next quote after restart censors active orders if valid observation coverage has a gap over 15 seconds.

Only one writer can own a cohort directory. Restart with the same command/directory to retain its original start time and manifest. If detector, recorder or policy/spec hashes change, the runner refuses to resume that cohort. Do not edit parameters to rescue interim results; a deliberate new hypothesis requires a new directory and separate evidence.

## Interpretation

- A quote-sampled hypothetical fill is not a real broker fill. Polling can miss price excursions between observations even when all polls succeed.
- Observed scenario uses bid/ask directly. Stress holds bid fixed and widens spread/commission by 1.5x. These can produce different fills; neither is an actual portfolio return.
- A setup cannot enter before its observed admission time. Historical candles provide warmup only. Late discovery over 90 seconds, missing fresh quotes, excessive observed cost, incomplete ranges, ambiguous clocks and stale/corrected data are recorded explicitly.
- A gap over 15 seconds in valid observations censors active orders and excludes them from net-R statistics and sample gates. It may be common during poor connectivity; investigate coverage rather than treating missing outcomes as wins, losses or expiries.
- Source bars are immutable. A broker revision raises a BAR_REVISION event and suppresses setup admission from that snapshot instead of rewriting earlier evidence.
- Commission remains a frozen modeled $7 round-turn/lot converted with frozen tick specs. It is not a measurement of actual broker fees.
- REVIEW_READY requires each execution scenario to have at least 100 complete trades, three symbols with at least 20 complete trades, positive aggregate mean and a majority of those symbols positive. This requests human research review; it never enables live trading.
- Interim counts and returns are descriptive. Do not repeatedly select a winning candidate or change rules while collecting. This prospective gate does not erase failed historical gates.

The full contract is [the frozen prospective protocol](../research/2026-09-18-sb-prospective-protocol.md).

## Files and operation

Each directory contains `shadow.sqlite3` (WAL database), `manifest.json` and `recorder.lock`. SQLite is authoritative for the manifest and cohort start. No secrets are written to the manifest. Errors record exception class names rather than raw HTTP messages.

WAL uses NORMAL synchronization so every quote does not wait for a disk flush. This supports ordinary process-crash recovery, but a sudden host power loss can discard recent uncheckpointed observations. After such a failure, review coverage and cohort integrity before using its results; use a separate cohort if continuity cannot be established.

Quotes are polled every two seconds across nine symbols; bars every 30 seconds. Retaining every observation can produce roughly 389,000 quote rows per day. Monitor disk space; there is no silent pruning. Export/archive a stopped cohort as a unit, including a checkpointed database or SQLite backup, rather than copying only the live main database while its WAL is active.

The dashboard's heartbeat can remain recent while quotes fail. Check per-symbol last-valid age and latest quote reason, and inspect the event table. Stale market quotes outside trading hours are expected, not executable evidence.

If bridge timestamps no longer encode seasonal broker-local wall time, quotes will be rejected as stale/future. Do not change clock assumptions mid-cohort. Investigate the bridge clock and start a separately documented cohort if a correction is necessary.

## Running cohort (September 18, 2026)

The prospective recorder is running in tmux session `sb-shadow-20260918`, using `data/shadow/sb_prospective_20260918/` and port 8772. Logs append to `recorder.log` in that directory. Smoke-check directories are separate and excluded from the prospective cohort.

To inspect the session, use `tmux attach -t sb-shadow-20260918`; detach with Ctrl-B then D. To stop it gracefully, use `tmux send-keys -t sb-shadow-20260918 C-c`. The shell session then ends. A restart can use the foreground command above or a new tmux session with the same directory and unchanged frozen files. There is no automatic system-boot service.

At deployment verification, all nine symbols had fresh quotes. USDCAD and GBPJPY candle contexts were stale/revised and were correctly withheld. The dashboard therefore showed DEGRADED feed health even while fresh quote capture continued. Investigate source history rather than relaxing the admission checks.
