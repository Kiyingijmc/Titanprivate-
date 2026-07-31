# ==============================================================================
# FILE: src/core/state_manager.py
# TYPE: OPTIMIZATION UPDATE (I/O Reduction)
# AUDIT: 
#   1. Replaced "Connection-Per-Call" with Persistent Singleton Connection.
#   2. Drastically reduced I/O latency using retained WAL mode.
#   3. Preserved all V14.2 schema migrations and logic logic.
# STATUS: PRODUCTION READY
# ==============================================================================

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
                    grade TEXT DEFAULT '',
                    comment TEXT DEFAULT ''
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

            # --- MIGRATION GUARD (Retained) ---
            # Checks for columns added in newer versions (v14.1/14.2/14.4)
            cursor = self.conn.execute("PRAGMA table_info(active_orders)")
            existing_cols = [col[1] for col in cursor.fetchall()]

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
        """
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO active_orders
                (ticket_id, symbol, strategy, order_type, time_placed, status, phase, ratchet_level,
                 initial_entry, initial_tp, initial_sl, lots, grade, comment)
                VALUES (?,?,?,?,?,?,
                    COALESCE((SELECT phase FROM active_orders WHERE ticket_id=?),0),
                    COALESCE((SELECT ratchet_level FROM active_orders WHERE ticket_id=?),0),
                    ?, ?, ?, ?, ?, ?
                )
            """, (ticket, sym, strat, otype, time.time(), status, ticket, ticket,
                  entry, tp, sl, lots, grade, strat))
            self.conn.commit()
        except Exception as e:
            print(f"[DB ERROR] Register: {e}")

    def get_order(self, ticket):
        """Returns the full active_orders row as a dict, or None."""
        try:
            r = self.conn.execute("SELECT * FROM active_orders WHERE ticket_id=?", (ticket,)).fetchone()
            return dict(r) if r else None
        except Exception:
            return None

    def backfill_position_state(self, ticket, entry=0.0, tp=0.0):
        """
        Heartbeat sync: fills initial_entry/initial_tp ONLY where still zero
        (the EA's OPENED message carries no prices) and marks the ticket ACTIVE
        so the ratchet manager can engage. Never overwrites known values.
        """
        try:
            self.conn.execute("""
                UPDATE active_orders SET
                    initial_entry = CASE WHEN initial_entry = 0 THEN ? ELSE initial_entry END,
                    initial_tp    = CASE WHEN initial_tp = 0 THEN ? ELSE initial_tp END,
                    status = 'ACTIVE'
                WHERE ticket_id = ?
            """, (entry, tp, ticket))
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
                self.conn.execute("""
                    INSERT OR IGNORE INTO trade_history
                    (ticket_id, symbol, strategy, close_time, pnl, entry, sl, tp, lots, grade, comment)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (ticket, trade['symbol'], trade['strategy'], time.time(), pnl,
                      trade['initial_entry'], trade['initial_sl'], trade['initial_tp'],
                      trade['lots'], trade['grade'], trade['comment']))
                self.conn.execute("DELETE FROM active_orders WHERE ticket_id=?", (ticket,))
                self.conn.commit()
        except Exception as e:
            print(f"[DB ERROR] Archive: {e}")

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
            rows = self.conn.execute("SELECT * FROM active_orders WHERE status='PENDING'").fetchall()
            return [dict(r) for r in rows]
        except: return []

    def save_risk_anchor(self, trading_day_key, day_start_equity):
        """Persist today's drawdown anchor (RISK-01).

        Called on change, not per heartbeat: once when the boot anchor is first
        established and once at the 23:45 daily reset.
        """
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO risk_state
                (id, trading_day_key, day_start_equity, updated_at)
                VALUES (1, ?, ?, ?)
            """, (str(trading_day_key), float(day_start_equity), time.time()))
            self.conn.commit()
        except Exception as e:
            print(f"[DB ERROR] SaveRiskAnchor: {e}")

    def get_risk_anchor(self):
        """The persisted drawdown anchor, or None if never saved / unreadable.

        None means "no usable anchor" and the caller must fall back to the
        existing first-heartbeat behaviour -- never to a guessed number.
        """
        try:
            r = self.conn.execute(
                "SELECT trading_day_key, day_start_equity, updated_at "
                "FROM risk_state WHERE id=1").fetchone()
            return dict(r) if r else None
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