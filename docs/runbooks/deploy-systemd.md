# Deploy Titan via systemd

## Prerequisite: WSL systemd

Systemd must be enabled in WSL. Check `/etc/wsl.conf` contains:

```ini
[boot]
systemd=true
```

If missing, add it, run `wsl --shutdown` from Windows, and reopen the terminal.

## Install & enable

```bash
sudo cp deploy/systemd/titan-live.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now titan-live
```

Demo stage: same commands with `titan-demo.service` — but read the caveats below first.

## Watchdog semantics

- `Type=notify`: the controller sends `READY=1` via sd_notify when it reaches ACTIVE.
- The heartbeat loop sends `WATCHDOG=1` every 10s; `WatchdogSec=90` means systemd
  restarts the service after 90s of silence — a wedged event loop self-heals.
- `Restart=on-failure` + `RestartSec=10` also covers crashes and watchdog kills.

## Health checks

```bash
curl -s localhost:8787/readyz     # ready once controller is ACTIVE
systemctl status titan-live       # service state at a glance
```

## Demo-stage caveats

`titan-demo.service` points at `/home/kiyingijmc/projects/Titan_demo` — a SEPARATE
checkout with its own `.venv`, different ZMQ ports in its `config/config.yaml`,
its own SQLite state DB, and an FBS-Demo login. Never point live and demo at the
same MT5 terminal, and never enable the demo unit against the live checkout.

## Log access

```bash
journalctl -u titan-live -f            # follow live logs
journalctl -u titan-live -n 100 --no-pager   # last 100 lines
```

## Rollback

```bash
sudo systemctl stop titan-live
git log --oneline -10                  # pick the last known-good commit SHA
git checkout <sha> -- .                # restore working tree to that commit
sudo systemctl start titan-live
```
