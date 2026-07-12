# Deploy Titan via systemd

## Prerequisites

Ensure WSL has systemd enabled. Check `/etc/wsl.conf` on the Windows host:
```ini
[boot]
systemd=true
```
If missing, add it and restart WSL: `wsl --shutdown` then restart your terminal.

## Install & Enable

Copy the unit files and reload systemd:
```bash
sudo cp deploy/systemd/titan-live.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now titan-live
```

For demo staging (separate checkout with different ZMQ ports and config):
```bash
sudo cp deploy/systemd/titan-demo.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now titan-demo
```

## Watchdog & Restart Semantics

- **READY=1 on ACTIVE**: When the system controller reaches ACTIVE, it sends `sd_notify` with `READY=1`.
- **WATCHDOG=1 every 10s**: The heartbeat loop sends `WATCHDOG=1` every 10 seconds to reset the watchdog timer.
- **90s timeout**: If systemd receives no watchdog reset for 90 seconds, it forcefully restarts the service.
- **Self-healing**: A wedged event loop that stops responding will be caught by the watchdog and automatically restarted; no manual intervention needed.

## Health Check

Once running, verify the service is healthy:
```bash
curl -s localhost:8787/readyz
```

## Demo-Stage Caveats

The demo unit points to `/home/kiyingijmc/projects/Titan_demo` — a **separate checkout** with:
- Different ZMQ socket ports (avoid binding conflicts with live)
- Separate SQLite state DB
- **FBS-Demo login** configured in its `config/config.yaml` (never share the live MT5 terminal)
- Own `.env` with test Telegram token (or none)

Never enable both live and demo against the same MetaTrader 5 terminal.

## Log Access & Troubleshooting

View live logs (follow mode):
```bash
journalctl -u titan-live -f
```

View recent logs:
```bash
journalctl -u titan-live -n 50 --no-pager
```

Check service status:
```bash
systemctl status titan-live
```

## Rollback

To stop the service and revert to a previous stable tag:
```bash
sudo systemctl stop titan-live
git checkout v14.4  # or any prior tag
# Restart after code restore
sudo systemctl start titan-live
```
