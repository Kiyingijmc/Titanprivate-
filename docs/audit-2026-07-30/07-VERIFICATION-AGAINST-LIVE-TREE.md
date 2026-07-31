# Verification of the 2026-07-30 audit against the live tree

**Reviewer:** in-repo session, 2026-07-30
**Tree verified:** `main` @ `ab2ad69` (the audit cites `cc59155`; both are current-generation main)
**Method:** every claim below was re-derived from the working tree or from a live process, not accepted from the audit text.

**Verdict on the audit: it is accurate and unusually well-grounded.** Every structural finding I sampled — 24 of them, spanning all five severity tiers — reproduced exactly as described, at the cited file and line. I found no fabricated findings and no misread code. The corrections below are refinements of scope and blast radius, not reversals; two of them make the P0 *worse*, one makes it *smaller*, and one changes which failure modes are live right now.

---

## 1. Confirmed against the tree

| ID | Claim | Verified at | Status |
|---|---|---|---|
| P0 | `.env` with a Telegram token committed in baseline `7dd9527` | `git show 7dd9527:.env` → `TELEGRAM_TOKEN=807727…` | **CONFIRMED** |
| P0 | Same token still in tracked `data/logs/system.log` at HEAD | `git show HEAD:data/logs/system.log` | **CONFIRMED — and undercounted, see §2.1** |
| P0 | 10 gitignored-but-tracked runtime artifacts | `git ls-files -i -c --exclude-standard` | **CONFIRMED** |
| P0 | `.pyc` of the three deleted strategies still tracked | `crt`, `ict_ote`, `unicorn` × 2 Python versions | **CONFIRMED — count is 58, not 43** |
| SEC-05 | ZMQ binds `tcp://*` on all three ports | `bridge_zmq.py:25,36,53` | **CONFIRMED — and live right now, see §3** |
| SEC-05 | `update_symbol_specs` has zero bounds checks | `risk_manager.py:62-76` — `float()` coercion only | **CONFIRMED** |
| SEC-05 | `config.yaml` declares `host: "127.0.0.1"` and code never reads it | `config.yaml:27` vs `bridge_zmq.py` | **CONFIRMED** |
| SEC-04 | Neither systemd unit has `User=`/hardening/`StartLimit*` | `grep -cE … deploy/systemd/*.service` → `0` and `0` | **CONFIRMED** |
| SEC-07 | `.claude/settings.json` auto-approves `git add`/`git commit` | `.claude/settings.json:6-7` | **CONFIRMED** |
| CTRL-03 | Telegram auth fails open when `TELEGRAM_CHAT_ID` unset | `telemetry.py:36` `os.getenv(...)` → `None`; `:142-143` compares `str(...)` both sides; `:47` `is_active` checks only the token | **CONFIRMED** |
| CTRL-04 | `SettingsStore.validate` returns `None` (accept) for any unrecognised key | `settings.py:69` — literally `return None  # restart-tier keys: saved as-is` | **CONFIRMED** |
| CTRL-02 | `close_all_market_orders` counts sends, not closes | `system_controller.py:1094-1101` — `send_command` return discarded, `count += 1` unconditional | **CONFIRMED** |
| RISK-01 | `day_start_equity` is in-memory only | `risk_manager.py:36,51-52`; no persistence anywhere in `src/` | **CONFIRMED** |
| RISK-02 | Count caps receive only filled positions | `system_controller.py:419` passes `self.current_open_positions`; `current_pending_orders` appears at `:392` (aggregate risk) but never at `:419` or `arbiter.py:248` | **CONFIRMED — precisely as described** |
| RISK-03 | Correlation gate fails open | `correlation.py:105-106` `if self.matrix is None: return True, "Safe (No Matrix)"` | **CONFIRMED** |
| RISK-05 | Currency saturation is substring-matched, `len==6` only, threshold hardcoded | `exposure.py:33` `self.max_currency_saturation = 2`; `:107-120` | **CONFIRMED** |
| RISK-07 | The ask is discarded | `system_controller.py:690` reads `msg.get('b', 0)` only | **CONFIRMED** |
| RISK-09 | EA heartbeat has no magic filter | `Titan_Gateway.mq5:180` `PositionsTotal()` with no `POSITION_MAGIC` test; `InpMagic` used only at `:117` for outbound `req.magic` | **CONFIRMED** |
| RISK-10 | Two timezones in one buffer | `data_store.py:79` `pd.to_datetime(unit='s')` (naive UTC) vs `candle_maker.py:113,115` `datetime.fromtimestamp(...)` (local) | **CONFIRMED** |
| RISK-11 | `round(lots, 2)` | `risk_manager.py:203` | **CONFIRMED** |
| ARCH-01 | No client order ID in the payload | `system_controller.py:449-455` — `magic` is the config constant, `comment` is the strategy name | **CONFIRMED** |
| EXIT-01 | `send_command` return value never checked | all 11 call sites in `system_controller.py` (`:563,589,595,748,1099,1106,1115,1118`…) discard it | **CONFIRMED** |
| ENTRY-01 | EA dispatches by substring, CANCEL/CLOSE_POS are sequential `if`s | `Titan_Gateway.mq5:56,252,299,317,326` | **CONFIRMED** |
| ENTRY-03 | Store creates M5 and H1 only | `data_store.py:17,26-27,34-35` | **CONFIRMED** |
| EXEC-01 | `poll_commands()` runs before `poll_data()` | `system_controller.py:336` then `:341` | **CONFIRMED** |
| OBS-01 | `trade_history` has 11 columns; `archive_trade` drops `time_placed` and `ratchet_level` | `state_manager.py:65-79`, `:199-205` | **CONFIRMED** |
| OPS-01 | No demo/live guard anywhere | `grep -rniE "ACCOUNT_TRADE_MODE\|is_demo\|expected_account_mode" src/ mql5_bridge/ main.py` → nothing | **CONFIRMED** |
| OPS-02 | No CI | `ls .github` → no such directory | **CONFIRMED** |
| OPS-03 | Zero `ZMQBridge` tests | `grep -rln "ZMQBridge" tests/` → nothing | **CONFIRMED** |
| OPS-09 | `docs/RESUME.md` stale | `:4` still says `harden/normalize-price-crash` "(NOT merged to main)"; the two files it cites are absent from the tree | **CONFIRMED** |
| ARCH-07 | No signal handling | `grep -rnE "SIGTERM\|SIGINT\|add_signal_handler\|atexit" src/ main.py` → nothing | **CONFIRMED** |
| STRAT-01 | The research harness does not exercise the ratchet | `grep -c "ratchet\|runner\|TradeManager" scripts/research_run.py` → **0**; `replay_managed`/`replay_overlay` live at `poc_sb_stops.py:215,264` | **CONFIRMED** |
| §1.2 | `tradebot/` imported by nothing on the live path | `grep -rn "from tradebot\|import tradebot" src/ main.py scripts/ bridge/` → nothing | **CONFIRMED** |
| B2 | `drawdown_throttle` ships disabled | `config.yaml:68` `enabled: false` | **CONFIRMED** |

---

## 2. Corrections

### 2.1 The token exposure is larger than stated in one dimension, and smaller in another

**Larger — occurrence count.** The audit says `data/logs/system.log` contains "approximately 30 occurrences." The actual count at HEAD is **179**. `data/logs/titan_system.log` contains **0** (the audit does not claim otherwise; noting it for scope). The tracked-`.pyc` count is **58**, not 43.

**Smaller — public exposure window.** The audit repeatedly frames this as *"publicly exposed … since the first commit"* and *"lived through six trees / 350 commits"* on a public repository. The first half is true of **git history**; it is not true of **public exposure**. `.git/refs/remotes/origin/` was first written **2026-07-30 05:10 local** — the remote was added and pushed today. Before that the repository had no remote at all (`scripts/run_pr_checks.sh:8` says so, and the audit itself notes that statement "is now false"). So the credential sat in a *local* history for months and in a *pushed* history for roughly half a day.

That reduces the blast radius considerably. It does not change any remediation step: rotate, untrack, rewrite, scan.

### 2.2 The token in the repo is not the token in `.env`

The audit assumes the exposed credential is the live one. It is not the one currently configured:

| Source | Token prefix |
|---|---|
| `7dd9527:.env` (history) **and** `HEAD:data/logs/system.log` | `807727…` |
| current working `.env` | `862623…` |

So at some point the configured token changed. **This does not close the P0**, because two different things are being conflated:

- *changing `.env`* — done
- *revoking `807727…` at BotFather* — **unknown, and unverifiable from here** (no network egress in this environment)

If `807727…` was never revoked, it is a live credential in a pushed public-or-private history and in HEAD, and every impact in §3 of `01-SECURITY-INCIDENT-P0.md` applies to it. **The single check that resolves this is `getMe` on the old token: a 401 closes it, a 200 means the P0 is fully live.** Until that is run, treat the P0 as open.

Good news either way: the *current* token (`862623…`) does not appear in any tracked file.

### 2.3 `verify_integrity.py` is at the repo root

SEC-06's finding is correct; the file is `./verify_integrity.py`, not `scripts/verify_integrity.py`. The Quick Wins table (#15) gets this right; §9.6 gives no path. Trivial, noted only so a fix session doesn't waste a minute.

### 2.4 Test count

The audit reports 682 tests. Current `main` is **683** (S015 added one). Immaterial to any finding.

---

## 3. What the audit could not see, and what it changes

The audit lists "whether the demo soak is running, and against what" as unassessable. It is assessable from inside the box, and the answer changes which failure chains are live **right now**:

**The bot is running.** PID 1151503, `.venv/bin/python -u main.py`, uptime ~17.5 h at time of writing.

**It is not running under systemd.** It was launched from an interactive shell (output redirected to a session scratchpad log). Consequences, all of which cut against the audit's model in both directions:

- The liveness net the audit credits — `Type=notify`, `WatchdogSec=90`, `sd_notify("WATCHDOG=1")` — **is not in play.** Nothing will kill and restart a wedged loop. OBS-07/OBS-08 are moot for this process; a wedge is simply permanent.
- `Restart=on-failure` is **not in play** either, so RISK-01's restart-laundering chain — the audit's #2 finding by expected impact — **cannot fire for the currently-running process.** A crash is a stop, not a re-anchor. RISK-01 remains exactly as severe the moment this is run under the unit file, which is the documented deployment.
- `MemoryMax=2G` is not applied.

**SEC-05 is not theoretical — it is live.** `ss -tlnp` right now:

```
0.0.0.0:32768   pid=1151503     ← PUSH  (Py→EA commands)
0.0.0.0:32769   pid=1151503     ← PULL  (EA→Py data)
0.0.0.0:32770   pid=1151503     ← REQ/REP (order handshake)
127.0.0.1:8770  pid=1151503     ← GUI
127.0.0.1:8787  pid=1151503     ← health
```

The GUI and health probe correctly bind loopback. All three trading sockets are on every interface, unauthenticated, right now, with the process holding real positions. The one-message spec-poisoning attack in SEC-05 is executable by anything that can open a socket to this host.

**Two of the audit's predicted symptoms are visibly occurring in the live log.**

1. `🚨 WATCHDOG: HEARTBEAT LOST. ATTEMPTING RECOVERY...` repeats through the session. That is `_reboot_terminal()` — the Windows `taskkill` path that `CLAUDE.md` documents as a no-op on Linux — firing on a 60-second timer with nothing behind it. Exactly §1.5 and §3.5's "a no-op called repeatedly and forever," observed.
2. `[CMD] status []`, `[CMD] bxhus []`, `[CMD] dsfgh []` — Telegram commands, including junk, arriving and being recorded **only** by `telemetry.py:147`'s `print()`. OBS-09 confirmed in production, with live evidence that the command channel is being typed into.

---

## 4. Assessment of the non-audit documents

**`04-REMEDIATION-ROADMAP.md`** — the sequencing is sound and the effort estimates are, if anything, conservative for this codebase (the exposure suite at 638 LOC really does make A5 a one-hour change). Two notes:

- Quick Win #13 (`drawdown_throttle.enabled: true`) conflicts with the audit's own §11.3 framing: turning on a *new* risk parameter while RISK-01/02/03 are unenforced adds a variable to an unenforced baseline. Do it after A4/A5, not as a quick win.
- Quick Win #3 says `exposure.py:92,100`. The change is at the **call sites** (`system_controller.py:419`, `arbiter.py:145/248`) plus signature changes; the 20-minute estimate holds only if the caps' tests are extended too, which is the point of doing it.

**`05-STRATEGY-ARSENAL.md`** — the strongest item in the whole package is EXP-0 ("Coin Flip": run the ratchet on random entries matched to SilverBullet's marginals). It is one day of work against an existing rig, it is a genuine falsification test of the project's central assumption, and its third outcome would invalidate the entire strategy programme. It should be sequenced **with** STRAT-01, not after the arsenal. The seven strategies themselves are reasonable and honestly costed, but every one of them is downstream of a measured live expectancy that does not exist yet.

**`06-PRE-REGISTRATION-TEMPLATE.md`** — good, and close in spirit to what `docs/research/2026-07-11-silverbullet-h1-stop-study.md` already did informally. Adopting it costs nothing.

**`03-FINDINGS-REGISTER.xlsx`** — not opened (binary). 101 rows claimed; the 34 I sampled from the prose all reproduced.

---

## 5. What I would do with this

The audit's Stage A is right, but it is 19 items and this repo lands work through `mig` sessions one task at a time. The ordering that respects both:

1. **Resolve the P0 question first, today** — `getMe` on `807727…`. Everything else in the security tier is contingent on the answer. If it returns 200, revoke, then `getWebhookInfo`/`deleteWebhook` on the new token.
2. **Untrack + history rewrite** (A2) — independent of the answer, and cheap.
3. **SEC-05 bounds check + specific-interface bind** — the only finding that is *actively exploitable against a running process holding positions*. The audit's own panel put this first on sequencing and I agree, with more force now that the sockets are confirmed open.
4. **RISK-02** (pass pendings into both count gates) — the audit's architect is right that this is the one that fires weekly rather than on a crash, and it is the smallest diff in Stage A.
5. **OBS-01 journal schema** — genuinely deadline-sensitive. The soak is running and accruing trades into a schema that cannot answer the question the soak exists to answer.
6. **RISK-01 + systemd hardening together** — RISK-01 is dormant while the process runs outside systemd, and becomes the #2 finding the moment it is run properly. Fix both before the next `systemctl` start, not after.

STRAT-01 and EXP-0 are the research track and can run in parallel; neither touches the live path.

---

*This appendix was produced by re-deriving each claim from the tree. Where a claim could not be checked from inside this environment — repository visibility, whether the old token is revoked, MQL5 runtime behaviour — it is marked unverified above rather than assumed either way.*
