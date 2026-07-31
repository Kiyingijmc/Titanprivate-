# P0 SECURITY INCIDENT — Live Credential Exposure

**Severity:** P0 — act today
**Discovered:** 2026-07-30, during independent audit
**Status at discovery:** Active. Credential publicly readable at time of writing.
**Estimated remediation:** 10 minutes for containment, ~2 hours for full cleanup

---

## 1. Summary

**A live Telegram bot token is publicly exposed in the `Titanprivate-` repository, in two independent locations, and has been since the first commit.** The repository is public despite its name.

The token controls the bot's command channel, which includes `/panic`, `/closeall`, `/close`, `/cancel` and `/pause` — every capital-affecting remote control the system has.

---

## 2. Exposure inventory

### 2.1 Primary source — `.env` committed to history

```
$ git log --all --oneline --follow -- .env
e2e56b7 fix: normalize_price crash + broker-spec-only sizing; secrets hygiene; drop dead duplicate
7dd9527 baseline
```

`.env` was committed in `7dd9527` ("baseline") and survived in **six trees** before removal in `e2e56b7` ("secrets hygiene"). The cleanup commit removed the file from the working tree but **not from history**, and the credential was **not rotated**.

Recovered contents (redacted):

| Variable | Value | Assessment |
|---|---|---|
| `TELEGRAM_TOKEN` | `807727…` | **LIVE CREDENTIAL — exposed** |
| `TELEGRAM_CHAT_ID` | `143638…` | Exposed. Not itself a secret (see §3) |
| `MT5_LOGIN` | `x` | Placeholder — **no broker credential leaked** |
| `MT5_PASS` | `x` | Placeholder — **no broker credential leaked** |

**The one piece of good news in this incident: no broker credentials were ever committed.**

### 2.2 Secondary source — still in HEAD

`data/logs/system.log:147–177` contains approximately 30 occurrences of the same token.

**Mechanism:** `telemetry.py:37` builds `self.base_url = f"https://api.telegram.org/bot{self.token}"`. The token is embedded in **every request URL**, so any library that logs a URL logs the credential. The occurrences are `requests`/`urllib3` retry warnings emitted during a DNS/connectivity outage against `api.telegram.org`.

**This file is tracked in the current tree.** Removing it from history alone would not have sufficed; it must be untracked as well.

### 2.3 Structural cause — still live

Two mechanisms remain in place and will reproduce this:

1. **Secret-in-URL with no log redaction.** `telemetry.py:37`. One `logging.basicConfig()` call or one dependency upgrade that logs request URLs reinstates the leak.
2. **`.gitignore` does not untrack.** All ten sensitive files below are matched by `.gitignore` rules that were added *after* they were committed. `git ls-files -i -c --exclude-standard` returns every one of them.

Contributing factor: `.claude/settings.json:6–7` auto-approves `Bash(git add *)` and `Bash(git commit *)`, permitting unattended commits without secret scanning. This is the plausible proximate cause of the original `.env` commit.

---

## 3. Impact assessment

**What an attacker holding the token CAN do:**

| Capability | Mechanism | Consequence |
|---|---|---|
| **Seize the command channel** | `setWebhook` | All updates redirect away from your `getUpdates` poll. **You silently lose all remote control including `/panic`.** Your bot sees only empty poll results; there is no fallback alert channel. |
| **Impersonate the bot to you** | `sendMessage` to chat `143638…` | Fabricated alerts, fake flatten confirmations, fake drawdown warnings — indistinguishable from real ones, especially since the bot's own flatten reports are unverified (finding CTRL-02). |
| **Read your commands** | `getUpdates` race | Attacker sees operational instructions in real time. |
| **Deny service** | Webhook + flood | Control channel unusable. |

**What an attacker holding the token CANNOT do:**

- **Issue commands as you.** `telemetry.py:142–144` compares `msg["from"]["id"]`, which Telegram asserts server-side from the sender's real account. Knowing the chat ID does not permit forging it. **The authorization allowlist holds.**
- **Reach your broker.** No MT5 credentials were leaked.

**One caveat:** finding CTRL-03 documents that authorization **fails open if `TELEGRAM_CHAT_ID` is unset** — `str(None) == "None"` matches an update lacking a `from` field. If that variable is ever missing, the allowlist stops holding. Remediation step 6 below addresses this.

### Other exposed artifacts

| Artifact | Leaks |
|---|---|
| `data/logs/titan_system.log` | Operational history |
| `data/db/trade_state.db` | **5 live `active_orders` rows, 24 `trade_history` rows** — your real trade record, entries, stops, P&L |
| `data/db/titan_core.db` | 63 `audit_log` rows |
| `boot_crash.log` | Windows username `JMC`, full desktop path |
| **43 tracked `.pyc` files** | **Compiled bytecode of `crt.py`, `ict_ote.py`, `unicorn.py`** — the strategies `CLAUDE.md:39` records as deleted on 2026-07-12. Recoverable with `uncompyle6`/`decompyle3`. **You deleted three strategies for being unvalidated and shipped them as bytecode.** |
| `.mig/config`, `.claude/settings.json`, systemd units | Username `kiyingijmc`, project layout, venv paths |

**Assessed benign:** `test_data.csv` (9,623 rows of OHLC — market data is not proprietary and contains no account identifiers) and `data/lake/frozen/**` (deliberately retained per `PROVENANCE.md`).

---

## 4. Remediation — execute in this order

> **Order matters.** Rotation must come first: the credential is already public, so history rewriting alone changes nothing. Making the repository private before rewriting prevents the rewrite itself from drawing attention to what was removed.

### Step 1 — Rotate (10 minutes) — DO THIS FIRST

1. Telegram → **BotFather** → `/mybots` → select your bot → **API Token** → **Revoke current token**
2. Copy the new token into `.env`
3. Immediately, using the **new** token, verify no webhook was planted:

```bash
curl -s "https://api.telegram.org/bot<NEW_TOKEN>/getWebhookInfo"
# Expect: {"ok":true,"result":{"url":"","has_custom_certificate":false,"pending_update_count":0}}

curl -s "https://api.telegram.org/bot<NEW_TOKEN>/deleteWebhook?drop_pending_updates=true"
```

### Step 2 — Make the repository private (2 minutes)

GitHub → repository → **Settings** → **General** → **Danger Zone** → **Change repository visibility** → Private.

### Step 3 — Establish full blast radius (20 minutes)

```bash
git log --all -p -- .env                    # confirm the committed secret
git rev-list --all | wc -l                  # 356 commits in scope

pipx run trufflehog git file://. --only-verified
pipx run detect-secrets scan --all-files > .secrets.baseline
docker run -v "$PWD:/repo" zricethezav/gitleaks:latest detect -s /repo -v
```

Record anything these surface beyond what is listed in §2.

### Step 4 — Untrack committed runtime artifacts (10 minutes)

```bash
# Confirm the problem first — every file here is gitignored AND tracked:
git ls-files -i -c --exclude-standard

git rm --cached boot_crash.log \
  data/logs/system.log data/logs/titan_system.log \
  data/db/trade_state.db data/db/titan_core.db \
  data/db/*-shm data/db/*-wal \
  data/history/ote_canonical_3yr.log

git rm -r --cached 'src/**/__pycache__'

git commit -m "chore: untrack runtime artifacts, databases, logs and bytecode"

# Verify it is now empty:
git ls-files -i -c --exclude-standard
```

### Step 5 — Rewrite history (30 minutes) — LAST, not first

```bash
pipx install git-filter-repo

git filter-repo --invert-paths \
  --path .env \
  --path data/logs/system.log \
  --path data/logs/titan_system.log \
  --path boot_crash.log \
  --path-glob 'data/db/*' \
  --path-glob 'src/**/__pycache__/*'

git push --force --all
git push --force --tags
```

**This rewrites all 22 branches.** Coordinate any clones you hold elsewhere.

**Important caveat:** GitHub retains unreachable objects and they remain accessible by direct SHA. To fully purge, either open a GitHub Support request citing this incident, or delete and recreate the repository from the rewritten local copy.

### Step 6 — Close the structural causes (45 minutes)

**a. Log redaction filter** — prevents recurrence of the `system.log` mechanism:

```python
# src/ops/redact.py
import logging, re

_TOKEN = re.compile(r'bot\d{8,12}:[A-Za-z0-9_-]{30,}')

class RedactSecrets(logging.Filter):
    def filter(self, record):
        if isinstance(record.msg, str):
            record.msg = _TOKEN.sub('bot<REDACTED>', record.msg)
        if record.args:
            record.args = tuple(
                _TOKEN.sub('bot<REDACTED>', a) if isinstance(a, str) else a
                for a in record.args)
        return True

def install():
    f = RedactSecrets()
    for name in ('', 'urllib3', 'requests', 'TitanAudit'):
        logging.getLogger(name).addFilter(f)
```

Call `install()` at the top of `main.py`. Verify by logging a synthetic token and confirming it is masked.

**b. Fail-closed chat ID** — closes finding CTRL-03. In `telemetry.py.__init__`:

```python
chat_id = os.getenv("TELEGRAM_CHAT_ID", "").strip()
if not chat_id.isdigit():
    raise RuntimeError("TELEGRAM_CHAT_ID must be set to a numeric chat ID")
self.allowed_chat_id = chat_id
```

And in `_process`, reject any update lacking a sender:

```python
sender = msg.get("from", {}).get("id")
if sender is None or str(sender) != self.allowed_chat_id:
    return
```

**c. Pre-commit secret scanning:**

```yaml
# .pre-commit-config.yaml
repos:
  - repo: https://github.com/gitleaks/gitleaks
    rev: v8.18.0
    hooks: [{id: gitleaks}]
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
  - repo: local
    hooks:
      - id: no-gitignored-files
        name: reject staging of gitignored files
        entry: bash -c 'f=$(git ls-files -i -c --exclude-standard); [ -z "$f" ] || { echo "Gitignored files staged:"; echo "$f"; exit 1; }'
        language: system
        pass_filenames: false
```

```bash
pipx run pre-commit install
```

**d. Remove commit auto-approval.** Edit `.claude/settings.json` and delete `"Bash(git add *)"` and `"Bash(git commit *)"` from the allowlist.

**e. Strip credential prints.** `test_telegram.py:48` prints `token[:5]`; `:53` prints the full chat ID. `RUN_TITAN.bat:36` runs this on every startup. Remove both prints, and rename the file to `scripts/check_telegram.py` so `unittest discover` and future CI cannot mistake a diagnostic script for a test.

### Step 7 — Move secrets out of `.env` (optional, recommended)

Migrate `TELEGRAM_TOKEN`, `TITAN_GUI_TOKEN` and `BRIDGE_AUTH_TOKEN` to the OS keyring (`keyring` on Linux/WSL, Credential Manager or DPAPI on Windows). If `.env` must remain, `chmod 600` it and confirm it is not on a path shared with the Windows host.

---

## 5. Verification checklist

Do not consider this closed until every line is true.

- [ ] Old token revoked; `getMe` with the old token returns 401
- [ ] `getWebhookInfo` on the new token returns an empty `url`
- [ ] Repository visibility is Private
- [ ] `git ls-files -i -c --exclude-standard` returns **zero rows**
- [ ] `git log --all -p -- .env` returns **nothing**
- [ ] `trufflehog git file://. --only-verified` reports **clean** across all branches
- [ ] Log redaction filter installed and verified against a synthetic token
- [ ] `TELEGRAM_CHAT_ID` required at startup; bot refuses to boot without it
- [ ] Updates lacking `from.id` are rejected
- [ ] `pre-commit install` complete; a deliberate test commit of a fake secret is **blocked**
- [ ] `git add`/`git commit` removed from `.claude/settings.json`
- [ ] Credential prints removed from `test_telegram.py`
- [ ] GitHub Support contacted regarding unreachable objects, **or** the repository recreated

---

## 6. Related findings

This incident is entangled with several audit findings that should be fixed alongside it:

| ID | Finding | Relationship |
|---|---|---|
| **CTRL-03** | Telegram authorization fails open when `TELEGRAM_CHAT_ID` is unset | The only control preventing token-holder command execution |
| **OBS-06** | Token embedded in every request URL; no redaction anywhere | The mechanism that produced the secondary exposure |
| **OBS-09** | No audit trail for any Telegram intervention | You could not reconstruct attacker actions if the allowlist had failed |
| **CTRL-07** | Telegram is the only alert channel; no fallback | A seized webhook means total, silent loss of visibility |
| **SEC-07** | `.claude/settings.json` auto-approves `git commit` | Plausible proximate cause |
| **SEC-02** | HTTP bridge defaults to `0.0.0.0` with a `CHANGE_ME` example token | Same class of default-insecure configuration |

---

## 7. Lessons for the process

1. **A "secrets hygiene" commit that does not rotate is not remediation.** `e2e56b7` removed the file and left the credential valid and publicly readable for the remaining 350 commits.
2. **`.gitignore` is not a remediation tool.** It prevents future staging; it does not untrack. Ten files were added to `.gitignore` and remained tracked.
3. **Secrets in URLs will end up in logs.** Not "might" — the log file proving it is in your repository. Any credential passed as a path segment must be paired with a redaction filter from day one.
4. **Automation with commit rights needs a secret scanner, not trust.** The allowlist that let an agent commit unattended is the same allowlist that let `.env` through.
