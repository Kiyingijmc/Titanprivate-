# ==============================================================================
# FILE: src/core/state_manager.py
# TYPE: OPTIMIZATION UPDATE (I/O Reduction)
# AUDIT: 
#   1. Replaced "Connection-Per-Call" with Persistent Singleton Connection.
#   2. Drastically reduced I/O latency using retained WAL mode.
#   3. Preserved all V14.2 schema migrations and logic logic.
# STATUS: PRODUCTION READY
# ==============================================================================

import json
import sqlite3
import time
from pathlib import Path

class StateManager:
    """
    Titan State Persistence Layer.
    
    AUDIT UPGRADE:
    - Moved from "Open/Close per query" to "Persistent Connection".
    - Eliminated file I/O overhead for high-frequency stop loss updates.
    """
    def __init__(self, db_path="data/db/trade_state.db"):
        self.db_path = str(db_path)
        
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        # 1. Establish Persistent Connection
        # check_same_thread=False allowed because access is serialized by the Event Loop
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row 
        
        # 2. Performance Pragma (Write-Ahead Logging)
        self.conn.execute("PRAGMA journal_mode=WAL;")
        self.conn.execute("PRAGMA synchronous=NORMAL;")
        
        # 3. Initialize Schema
        self._init_db()

    def _init_db(self):
        """Creates tables and runs migration guards (Retained from v14.1)."""
        try:
            # Active Orders Table
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS active_orders (
                    ticket_id INTEGER PRIMARY KEY,
                    symbol TEXT,
                    strategy TEXT,
                    order_type TEXT,
                    time_placed REAL,
                    status TEXT,
                    phase INTEGER DEFAULT 0,
                    ratchet_level INTEGER DEFAULT 0,
                    initial_entry REAL DEFAULT 0.0,
                    initial_tp REAL DEFAULT 0.0,
                    initial_sl REAL DEFAULT 0.0,
                    lots REAL DEFAULT 0.0,
                    remaining_volume REAL DEFAULT 0.0,
                    realized_pnl REAL DEFAULT 0.0,
                    partial_stage INTEGER DEFAULT 0,
                    partial_stage_requested INTEGER DEFAULT 0,
                    partial_stage_status TEXT DEFAULT 'NONE',
                    last_deal_id INTEGER DEFAULT 0,
                    grade TEXT DEFAULT '',
                    comment TEXT DEFAULT '',
                    entry_synced INTEGER DEFAULT 0
                )
            ''')

            # Trade History Table
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS trade_history (
                    ticket_id INTEGER PRIMARY KEY,
                    symbol TEXT,
                    strategy TEXT,
                    close_time REAL,
                    pnl REAL,
                    entry REAL DEFAULT 0.0,
                    sl REAL DEFAULT 0.0,
                    tp REAL DEFAULT 0.0,
                    lots REAL DEFAULT 0.0,
                    grade TEXT DEFAULT '',
                    comment TEXT
                )
            ''')

            # RISK-01: the daily drawdown anchor, so a restart cannot re-anchor
            # the circuit breaker to mid-day equity and mint a fresh allowance.
            # CHECK (id = 1) makes "exactly one row" a schema invariant, so a bug
            # elsewhere can never make "which anchor is current?" ambiguous.
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS risk_state (
                    id               INTEGER PRIMARY KEY CHECK (id = 1),
                    trading_day_key  TEXT,
                    day_start_equity REAL DEFAULT 0.0,
                    updated_at       REAL
                )
            ''')
            # A broker deal is the accounting identity for an exit.  Keeping a
            # durable uniqueness record is stronger than remembering only the
            # last delivered deal: deliveries may be duplicated or delayed.
            self.conn.execute('''
                CREATE TABLE IF NOT EXISTS processed_exit_deals (
                    ticket_id INTEGER NOT NULL,
                    deal_id INTEGER NOT NULL,
                    pnl REAL NOT NULL,
                    remaining_volume REAL NOT NULL,
                    processed_at REAL NOT NULL,
                    PRIMARY KEY (ticket_id, deal_id)
                )
            ''')

            # --- MIGRATION GUARD (Retained) ---
            # Checks for columns added in newer versions (v14.1/14.2/14.4)
            cursor = self.conn.execute("PRAGMA table_info(active_orders)")
            existing_cols = [col[1] for col in cursor.fetchall()]

            if 'management_profile' not in existing_cols:
                self.conn.execute("ALTER TABLE active_orders ADD COLUMN management_profile TEXT")

            if 'management_intent' not in existing_cols:
                self.conn.execute("ALTER TABLE active_orders ADD COLUMN management_intent TEXT")

            if 'comment' not in existing_cols:
                self.conn.execute("ALTER TABLE active_orders ADD COLUMN comment TEXT DEFAULT ''")
                print("[DB] Migration: Added 'comment' column.")

            if 'ratchet_level' not in existing_cols:
                self.conn.execute("ALTER TABLE active_orders ADD COLUMN ratchet_level INTEGER DEFAULT 0")

            if 'initial_entry' not in existing_cols:
                self.conn.execute("ALTER TABLE active_orders ADD COLUMN initial_entry REAL DEFAULT 0.0")

            if 'initial_tp' not in existing_cols:
                self.conn.execute("ALTER TABLE active_orders ADD COLUMN initial_tp REAL DEFAULT 0.0")

            # v14.4 journal columns (full trade record)
            if 'initial_sl' not in existing_cols:
                self.conn.execute("ALTER TABLE active_orders ADD COLUMN initial_sl REAL DEFAULT 0.0")
            if 'lots' not in existing_cols:
                self.conn.execute("ALTER TABLE active_orders ADD COLUMN lots REAL DEFAULT 0.0")
            if 'grade' not in existing_cols:
                self.conn.execute("ALTER TABLE active_orders ADD COLUMN grade TEXT DEFAULT ''")

            # v14.4 fill-price correction marker (audit D3) -- see
            # backfill_position_state. Persisted rather than in-memory so a
            # restart cannot re-open the one-shot correction window and let a
            # mid-trade heartbeat redefine the entry.
            if 'entry_synced' not in existing_cols:
                self.conn.execute(
                    "ALTER TABLE active_orders ADD COLUMN entry_synced INTEGER DEFAULT 0")
            for col, decl in [('remaining_volume', 'REAL DEFAULT 0.0'),
                              ('realized_pnl', 'REAL DEFAULT 0.0'),
                              ('partial_stage', 'INTEGER DEFAULT 0'),
                              ('partial_stage_requested', 'INTEGER DEFAULT 0'),
                              ('partial_stage_status', "TEXT DEFAULT 'NONE'"),
                              ('last_deal_id', 'INTEGER DEFAULT 0')]:
                if col not in existing_cols:
                    self.conn.execute(f"ALTER TABLE active_orders ADD COLUMN {col} {decl}")

            cursor = self.conn.execute("PRAGMA table_info(trade_history)")
            hist_cols = [col[1] for col in cursor.fetchall()]
            for col, decl in [('entry', 'REAL DEFAULT 0.0'), ('sl', 'REAL DEFAULT 0.0'),
                              ('tp', 'REAL DEFAULT 0.0'), ('lots', 'REAL DEFAULT 0.0'),
                              ('grade', "TEXT DEFAULT ''")]:
                if col not in hist_cols:
                    self.conn.execute(f"ALTER TABLE trade_history ADD COLUMN {col} {decl}")

            self.conn.commit()
            
        except Exception as e:
            print(f"[DB INIT ERROR] {e}")

    def register_order(self, ticket, sym, strat, otype, status="PENDING", entry=0.0, tp=0.0,
                       sl=0.0, lots=0.0, grade=""):
        """
        RETAINS FULL v14.1 logic:
        Uses COALESCE to preserve the specific 'phase' and 'ratchet_level'
        if the bot reboots while a trade is active.

        'entry_synced' is deliberately NOT preserved: this call (re)writes
        initial_entry from the send-time intended price, so the fill-price
        correction window in backfill_position_state must re-open with it.
        Latching it here would leave a re-registered ticket stuck on the
        intended price forever; resetting it self-heals on the next heartbeat.
        """
        try:
            existing = self.get_order(ticket)
            if existing:
                # A broker heartbeat/recovery must never replace immutable trade
                # identity (strategy, placement time, original risk inputs).
                self.conn.execute("""
                    UPDATE active_orders SET symbol=?, order_type=?, status=?,
                           initial_tp=CASE WHEN initial_tp=0 THEN ? ELSE initial_tp END,
                           initial_sl=CASE WHEN initial_sl=0 THEN ? ELSE initial_sl END,
                           remaining_volume=CASE WHEN remaining_volume=0 THEN lots ELSE remaining_volume END
                     WHERE ticket_id=?
                """, (sym, otype, status, tp, sl, ticket))
                self.conn.commit()
                return
            self.conn.execute("""
                INSERT OR REPLACE INTO active_orders
                (ticket_id, symbol, strategy, order_type, time_placed, status, phase, ratchet_level,
                 initial_entry, initial_tp, initial_sl, lots, remaining_volume,
                 realized_pnl, partial_stage, partial_stage_requested, partial_stage_status,
                 last_deal_id, grade, comment)
                VALUES (?,?,?,?,?,?,
                    COALESCE((SELECT phase FROM active_orders WHERE ticket_id=?),0),
                    COALESCE((SELECT ratchet_level FROM active_orders WHERE ticket_id=?),0),
                    ?, ?, ?, ?, ?, 0.0, 0, 0, 'NONE', 0, ?, ?
                )
            """, (ticket, sym, strat, otype, time.time(), status, ticket, ticket,
                  entry, tp, sl, lots, lots, grade, strat))
            self.conn.commit()
        except Exception as e:
            print(f"[DB ERROR] Register: {e}")

    def has_structure_profiles(self):
        rows = self.conn.execute("SELECT management_profile FROM active_orders WHERE management_profile IS NOT NULL").fetchall()
        return any(json.loads(row[0]).get('mode') == 'm15_structure_v1' for row in rows)

    def get_management_profile(self, ticket):
        row = self.conn.execute("SELECT management_profile FROM active_orders WHERE ticket_id = ?", (ticket,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def save_management_profile(self, ticket, profile):
        with self.conn:
            result = self.conn.execute(
                "UPDATE active_orders SET management_profile = COALESCE(management_profile, ?) WHERE ticket_id = ?",
                (json.dumps(profile), ticket))
            if result.rowcount != 1:
                raise ValueError(f'Unknown management ticket {ticket}')
        return self.get_management_profile(ticket)

    def get_management_intent(self, ticket):
        row = self.conn.execute("SELECT management_intent FROM active_orders WHERE ticket_id=?", (ticket,)).fetchone()
        return json.loads(row[0]) if row and row[0] else None

    def save_management_intent(self, ticket, intent):
        # Persist before dispatch. Failure must propagate: an unrecorded close
        # cannot be retried safely after a restart.
        with self.conn:
            changed = self.conn.execute(
                "UPDATE active_orders SET management_intent=? WHERE ticket_id=?",
                (json.dumps(intent), ticket))
            if intent.get('partial'):
                self.conn.execute("""UPDATE active_orders SET
                    partial_stage_requested=MAX(partial_stage_requested,?),
                    partial_stage_status='REQUESTED' WHERE ticket_id=?""",
                    (intent['level'] - 1, ticket))
            if changed.rowcount != 1:
                raise ValueError(f"Unknown management ticket {ticket}")

    def confirm_management_intent(self, ticket, level):
        with self.conn:
            self.conn.execute("""
                UPDATE active_orders SET ratchet_level=MAX(ratchet_level,?),
                    phase=MAX(phase,?), management_intent=NULL,
                    partial_stage=MAX(partial_stage,partial_stage_requested),
                    partial_stage_status=CASE WHEN partial_stage_requested>0
                        THEN 'CONFIRMED' ELSE partial_stage_status END
                WHERE ticket_id=?
            """, (level, level, ticket))

    def get_order(self, ticket):
        """Returns the full active_orders row as a dict, or None."""
        try:
            r = self.conn.execute("SELECT * FROM active_orders WHERE ticket_id=?", (ticket,)).fetchone()
            return dict(r) if r else None
        except Exception:
            return None

    def backfill_position_state(self, ticket, entry=0.0, tp=0.0):
        """
        Heartbeat sync from a live position (`entry` = POSITION_PRICE_OPEN,
        `tp` = the position's TP). Marks the ticket ACTIVE so the ratchet
        manager can engage, and reconciles the two "initial" prices.

        initial_tp: filled ONLY where still zero (the EA's OPENED message
        carries no prices); a known TP is never overwritten.

        initial_entry: for MARKET rows, CORRECTED ONCE to the broker's actual
        fill (audit 2026-08-07 D3). It used to be fill-if-zero too, which meant
        the send-time *intended* price written at EXECUTION:OPENED stood
        forever -- but the EA sends MARKET orders with deviation=20, so the
        broker may fill elsewhere. Every consumer keys off this column (the L1
        break-even stop, all three ratchet pct thresholds, the close-time
        R-multiple), so on a slipped BUY the "risk-free" break-even stop landed
        BELOW the real fill and locked in a loss.

        Three guards make the correction safe:
        - MARKET only. A LIMIT/STOP fills AT its resting price, so the
          heartbeat adds nothing there and the old semantics stand.
        - Once per ticket, latched in `entry_synced` (persisted, so a restart
          does not re-open the window). initial_entry is a fixed reference
          point; a later heartbeat must never redefine it.
        - entry > 0 only. A position dict missing `p` arrives as 0.0, and
          zeroing the entry would silently disable ALL management for the
          ticket (trade_manager skips rows whose entry is zero). The latch
          stays open so the next heartbeat can still supply the real price.
        """
        try:
            self.conn.execute("""
                UPDATE active_orders SET
                    initial_entry = CASE
                        WHEN order_type = 'MARKET' AND entry_synced = 0 AND ? > 0 THEN ?
                        WHEN initial_entry = 0 THEN ?
                        ELSE initial_entry END,
                    entry_synced  = CASE
                        WHEN order_type = 'MARKET' AND ? > 0 THEN 1
                        ELSE entry_synced END,
                    initial_tp    = CASE WHEN initial_tp = 0 THEN ? ELSE initial_tp END,
                    status = 'ACTIVE'
                WHERE ticket_id = ?
            """, (entry, entry, entry, entry, tp, ticket))
            self.conn.commit()
        except Exception as e:
            print(f"[DB ERROR] Backfill: {e}")

    def reconcile_state(self, mt5_tickets, grace_s=120.0):
        """
        Identifies tickets present in DB but missing in MT5 (Closed Externally).

        Rows younger than grace_s are exempt: a row registered by
        EXECUTION:OPENED is uncorroborated until the NEXT heartbeat (the EA
        heartbeats every 5s), so a recon tick landing inside that window would
        falsely sweep it — and nothing can re-register a swept PENDING row,
        because the heartbeat's `orders` entries carry no SL (RS013 round 3).
        The cost is bounded: an externally-deleted order is detected at most
        grace_s late.
        """
        ghost_tickets = []
        try:
            cutoff = time.time() - grace_s
            rows = self.conn.execute(
                "SELECT ticket_id, time_placed FROM active_orders").fetchall()
            for r in rows:
                tid = r['ticket_id']
                if tid not in mt5_tickets and (r['time_placed'] or 0) < cutoff:
                    ghost_tickets.append(tid)
        except Exception as e:
            print(f"[DB ERROR] Reconcile: {e}")
        return ghost_tickets

    def archive_trade(self, ticket, pnl):
        """Moves trade to history upon closure."""
        try:
            trade = self.conn.execute("SELECT * FROM active_orders WHERE ticket_id=?", (ticket,)).fetchone()
            if trade:
                total_pnl = float(trade['realized_pnl'] or 0.0) + float(pnl or 0.0)
                self.conn.execute("""
                    INSERT OR IGNORE INTO trade_history
                    (ticket_id, symbol, strategy, close_time, pnl, entry, sl, tp, lots, grade, comment)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (ticket, trade['symbol'], trade['strategy'], time.time(), total_pnl,
                      trade['initial_entry'], trade['initial_sl'], trade['initial_tp'],
                      trade['lots'], trade['grade'], trade['comment']))
                self.conn.execute("DELETE FROM active_orders WHERE ticket_id=?", (ticket,))
                self.conn.commit()
        except Exception as e:
            print(f"[DB ERROR] Archive: {e}")

    def record_exit_deal(self, ticket, deal_id, pnl, remaining_volume,
                         confirm_requested_stage=False):
        """Record one broker-confirmed partial deal without archiving the row.

        ``partial_stage`` means confirmed, never merely requested.  A partial
        event can confirm the currently outstanding local request, but an
        uncorrelated/manual partial never invents a stage.  Returns ``True``
        when applied, ``False`` for a duplicate, and ``None`` when no active
        trade exists.
        """
        try:
            row = self.get_order(ticket)
            if not row:
                return None
            with self.conn:
                if deal_id:
                    inserted = self.conn.execute("""
                        INSERT OR IGNORE INTO processed_exit_deals
                        (ticket_id, deal_id, pnl, remaining_volume, processed_at)
                        VALUES (?, ?, ?, ?, ?)
                    """, (int(ticket), int(deal_id), float(pnl), float(remaining_volume), time.time()))
                    if inserted.rowcount != 1:
                        return False
                confirmed = int(row.get('partial_stage') or 0)
                if confirm_requested_stage:
                    confirmed = max(confirmed, int(row.get('partial_stage_requested') or 0))
                self.conn.execute("""
                    UPDATE active_orders
                       SET realized_pnl=COALESCE(realized_pnl,0)+?,
                           remaining_volume=?, partial_stage=?,
                           partial_stage_status=?, last_deal_id=?
                     WHERE ticket_id=?
                """, (float(pnl), float(remaining_volume), confirmed,
                      'CONFIRMED' if confirm_requested_stage and confirmed else row.get('partial_stage_status') or 'NONE',
                      int(deal_id or 0), ticket))
            return True
        except Exception as e:
            print(f"[DB ERROR] ExitDeal: {e}")
            return False

    def get_day_stats(self):
        """Aggregates PnL stats for the last 24h."""
        start_time = time.time() - 86400
        stats = {'net': 0.0, 'wins': {}, 'losses': {}}
        try:
            rows = self.conn.execute("SELECT strategy, pnl FROM trade_history WHERE close_time > ?", (start_time,)).fetchall()
            for r in rows:
                strat = r['strategy'] if r['strategy'] else "Manual"
                pnl = r['pnl']
                stats['net'] += pnl
                if pnl >= 0: 
                    stats['wins'][strat] = stats['wins'].get(strat, 0) + 1
                else: 
                    stats['losses'][strat] = stats['losses'].get(strat, 0) + 1
        except Exception: pass
        return stats

    def prune_database(self):
        """Routine maintenance to prevent SQLite bloat."""
        week_ago = time.time() - (7 * 86400)
        try:
            self.conn.execute("DELETE FROM active_orders WHERE time_placed < ? AND status != 'ACTIVE'", (week_ago,))
            self.conn.commit()
        except Exception: pass

    # --- Standard Helpers ---

    def exists(self, t):
        try:
            res = self.conn.execute("SELECT 1 FROM active_orders WHERE ticket_id=?", (t,)).fetchone()
            return res is not None
        except: return False

    def delete_order(self, t):
        try:
            self.conn.execute("DELETE FROM active_orders WHERE ticket_id=?", (t,))
            self.conn.commit()
        except: pass

    def get_pending_orders(self):
        try:
            rows = self.conn.execute(
                "SELECT * FROM active_orders WHERE status IN ('PENDING','CANCEL_REQUESTED')").fetchall()
            return [dict(r) for r in rows]
        except: return []

    def save_risk_anchor(self, trading_day_key, day_start_equity):
        """Persist today's drawdown anchor (RISK-01). Returns True on success.

        Called on change, not per heartbeat: once when the boot anchor is first
        established and once at the daily rollover.

        RS-RISK-01 MEDIUM-3: this MUST report success. It used to swallow every
        exception into a print while the caller cached (key, equity)
        unconditionally, so a single transient "database is locked" left the
        anchor unpersisted for the rest of the day and never retried.
        """
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO risk_state
                (id, trading_day_key, day_start_equity, updated_at)
                VALUES (1, ?, ?, ?)
            """, (str(trading_day_key), float(day_start_equity), time.time()))
            self.conn.commit()
            return True
        except Exception as e:
            print(f"[DB ERROR] SaveRiskAnchor: {e}")
            return False

    def get_risk_anchor(self):
        """The persisted drawdown anchor, or None when no row has been saved.

        RS-RISK-01 MEDIUM-4: read failures PROPAGATE. Unlike the other helpers
        in this file, this one feeds a safety control, and "the table is
        unreadable" must not be indistinguishable from "nothing saved yet" --
        that combination left the whole fix silently disabled with zero
        operator signal. The caller distinguishes the two and alerts.
        """
        r = self.conn.execute(
            "SELECT trading_day_key, day_start_equity, updated_at "
            "FROM risk_state WHERE id=1").fetchone()
        return dict(r) if r else None

    def get_order_meta(self, t):
        """(strategy, time_placed) for a ticket, or None. Read-only helper for
        TradeManager's per-strategy policies (time exits)."""
        try:
            r = self.conn.execute(
                "SELECT strategy, time_placed FROM active_orders WHERE ticket_id=?",
                (t,)).fetchone()
            return (r['strategy'], r['time_placed']) if r else None
        except Exception:
            return None

    def get_ratchet_state(self, t):
        try:
            r = self.conn.execute("SELECT ratchet_level, initial_entry, initial_tp FROM active_orders WHERE ticket_id=?", (t,)).fetchone()
            return (r['ratchet_level'], r['initial_entry'], r['initial_tp']) if r else (0, 0.0, 0.0)
        except: return (0, 0.0, 0.0)

    def update_ratchet_level(self, t, lvl):
        try:
            self.conn.execute("UPDATE active_orders SET ratchet_level=? WHERE ticket_id=?", (lvl, t))
            self.conn.commit()
        except: pass

    def update_trade_phase(self, t, p):
        try:
            self.conn.execute("UPDATE active_orders SET phase=? WHERE ticket_id=?", (p, t))
            self.conn.commit()
        except: pass

    def mark_partial_requested(self, t, stage):
        """Durably record a sent partial request; it is not broker confirmation."""
        try:
            self.conn.execute(
                "UPDATE active_orders SET partial_stage_requested="
                "MAX(COALESCE(partial_stage_requested,0),?), partial_stage_status='REQUESTED' "
                "WHERE ticket_id=?",
                (int(stage), t))
            self.conn.commit()
        except: pass

    def mark_cancel_requested(self, t):
        """Keep a pending order risk-bearing until a later broker snapshot removes it."""
        try:
            self.conn.execute(
                "UPDATE active_orders SET status='CANCEL_REQUESTED' "
                "WHERE ticket_id=? AND status='PENDING'", (t,))
            self.conn.commit()
        except Exception:
            pass

    def get_partial_state(self, t):
        """Return (confirmed_stage, requested_stage) for one active trade."""
        try:
            row = self.conn.execute(
                "SELECT partial_stage, partial_stage_requested FROM active_orders "
                "WHERE ticket_id=?", (t,)).fetchone()
            if not row:
                return (0, 0)
            return (int(row['partial_stage'] or 0),
                    int(row['partial_stage_requested'] or 0))
        except Exception:
            return (0, 0)

    def get_trade_phase(self, t):
        try:
            r = self.conn.execute("SELECT phase FROM active_orders WHERE ticket_id=?", (t,)).fetchone()
            return r['phase'] if r else 0
        except: return 0
        
    def close(self):
        """Explicit close."""
        if self.conn:
            self.conn.close()

    def __del__(self):
        """Destructor safeguard."""
        try:
            self.conn.close()
        except: pass
