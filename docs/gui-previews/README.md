# Position-management GUI review — September 23, 2026

These screenshots use **simulated account and trade data**, supplied through intercepted HTTP/WebSocket responses in an isolated browser. They do not show the live account. The review sent no trading commands.

- [Desktop positions](positions-desktop.png): exposure summary, broker-stop coverage, pending management, and grouped trade rows.
- [Desktop trade details](management-desktop.png): original-target progress and broker values separated from pending requests.
- [Phone summary](positions-mobile.png): responsive summary and compact status bar.
- [Phone positions](positions-mobile-trades.png): tappable instruments, retained volume precision, and horizontal table scrolling.
- [Phone trade details](management-mobile.png): scrollable dialog with pending partial/stop changes and confirmation status.

The GUI now reads optional management telemetry from `/api/state`. This is a read-only projection of each ticket's durable profile, confirmed stage and pending intent. It never assigns a profile, enables a strategy or sends a management command. Missing/corrupt state appears as unavailable, and a short trade's progress requires an ask quote. Broker SL/TP and remaining volume stay separate from requested values.

Existing close/cancel actions retain their confirmation dialogs and read-only restrictions. New filter reset and inspection controls issue no commands. Keyboard Escape closes trade details and restores focus to the trigger. Small volume steps and prices retain up to eight decimal places. The phone status bar emphasizes equity; balance remains in the overview and desktop status bar.

Validation: 405 frontend tests passed in the full suite; the affected component suite was rerun after final responsive changes. Thirty backend tests passed. Production build succeeded. Chromium checks covered 1440×1000, 390×844 and 320×740, dialog opening/closing, focus return, unmatched/reset filters, cancelling a close dialog, no page overflow, and reduced-motion rendering. No browser JavaScript errors occurred. Vite still reports the existing large-bundle warning; route loading behavior was preserved.

The frontend build is in `frontend/dist`. New management telemetry requires the backend to load the updated code on its next restart. The GUI remains compatible with an older backend and shows unavailable management data until then. The running trading process and live strategy configuration were not restarted or changed for this GUI work.

## Overview and strategy follow-up

The overview now links directly to the open book and calls out positions without reported broker stops and management requests awaiting confirmation. Disconnected snapshots are labeled as last received data.

The strategy workspace has registry counts, search, classification filters, timeframe and priority columns, and a single owner for loading/refresh state. Failed refreshes retain the last received table with an explicit warning and a working refresh action. Controller response text is shown for enable/disable/promote requests, including refusals delivered in successful HTTP responses. Promotion retains typed-id confirmation, displays failures inside its dialog, and disables confirmation when read-only or submitting. No strategy is enabled or promoted by viewing or filtering the page.

The follow-up build passes. All 49 affected overview/registry component tests pass across the focused runs, including controller refusal, filter reset, failed refresh, promotion errors, read-only handling, and the overview attention links.

Production-build browser checks also passed with zero JavaScript errors and zero trading mutations. They exercised registry search/reset, typed promotion gating without submission, refresh failure/recovery, and phone overflow checks.

- [Updated overview](overview-desktop.png)
- [Strategy library on desktop](strategies-desktop.png)
- [Strategy library on phone](strategies-mobile.png)
