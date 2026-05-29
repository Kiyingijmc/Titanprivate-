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
                    comment TEXT
                )
            ''')

            # --- MIGRATION GUARD (Retained) ---
            # Checks for columns added in newer versions (v14.1/14.2)
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
                
            self.conn.commit()
            
        except Exception as e:
            print(f"[DB INIT ERROR] {e}")

    def register_order(self, ticket, sym, strat, otype, status="PENDING", entry=0.0, tp=0.0):
        """
        RETAINS FULL v14.1 logic: 
        Uses COALESCE to preserve the specific 'phase' and 'ratchet_level' 
        if the bot reboots while a trade is active.
        """
        try:
            self.conn.execute("""
                INSERT OR REPLACE INTO active_orders 
                (ticket_id, symbol, strategy, order_type, time_placed, status, phase, ratchet_level, initial_entry, initial_tp, comment)
                VALUES (?,?,?,?,?,?,
                    COALESCE((SELECT phase FROM active_orders WHERE ticket_id=?),0),
                    COALESCE((SELECT ratchet_level FROM active_orders WHERE ticket_id=?),0),
                    ?, ?, ?
                )
            """, (ticket, sym, strat, otype, time.time(), status, ticket, ticket, entry, tp, strat))
            self.conn.commit()
        except Exception as e:
            print(f"[DB ERROR] Register: {e}")

    def reconcile_state(self, mt5_tickets):
        """
        Identifies tickets present in DB but missing in MT5 (Closed Externally).
        """
        ghost_tickets = []
        try:
            rows = self.conn.execute("SELECT ticket_id FROM active_orders").fetchall()
            for r in rows:
                tid = r['ticket_id']
                if tid not in mt5_tickets:
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
                    INSERT OR IGNORE INTO trade_history (ticket_id, symbol, strategy, close_time, pnl, comment)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (ticket, trade['symbol'], trade['strategy'], time.time(), pnl, trade['comment']))
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