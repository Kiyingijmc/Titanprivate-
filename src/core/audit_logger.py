# ==============================================================================
# FILE: src/core/audit_logger.py
# TYPE: PERFORMANCE UPDATE (I/O Reduction)
# AUDIT: 
#   1. Replaced "Connection-Per-Log" with Persistent WAL Connection.
#   2. Fixed thread-check constraints for Asyncio compatibility.
#   3. Retained "Dual-Write" (File + DB) architecture.
# STATUS: PRODUCTION READY
# ==============================================================================

import sqlite3
import json
import logging
from logging.handlers import RotatingFileHandler
from datetime import datetime
from pathlib import Path

class AuditLogger:
    """
    Titan Institutional Audit Trail.
    
    AUDIT UPGRADE:
    - Persistent Database Connection to eliminate Open/Close I/O overhead.
    - Write-Ahead-Logging (WAL) enabled for high-concurrency performance.
    """
    def __init__(self, db_path="data/db/titan_core.db"):
        self.db_path = str(db_path)
        
        # 1. Initialize Logging Hierarchy (File System)
        self._setup_logging()
        
        # 2. Initialize Database Connection (Persistent)
        # Ensure directory exists
        Path(self.db_path).parent.mkdir(parents=True, exist_ok=True)
        
        try:
            # check_same_thread=False allows use within Asyncio event loop
            self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
            
            # Performance Optimizations
            self.conn.execute("PRAGMA journal_mode=WAL;")
            self.conn.execute("PRAGMA synchronous=NORMAL;")
            
            # Create Table
            self._init_db_schema()
            
        except Exception as e:
            # Fallback to pure print/file logging if DB fails
            self.logger.critical(f"Audit Log DB Init Failed: {e}")
            self.conn = None

    def _init_db_schema(self):
        """Creates the audit table if it doesn't exist."""
        if self.conn:
            self.conn.execute("""
                CREATE TABLE IF NOT EXISTS audit_log (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    event_type TEXT, 
                    module TEXT, 
                    message TEXT, 
                    payload JSON
                )
            """)
            self.conn.commit()

    def _setup_logging(self):
        """Configures Python standard rotating file logger."""
        log_dir = "data/logs"
        Path(log_dir).mkdir(parents=True, exist_ok=True)
        log_file = f"{log_dir}/titan_system.log"

        # Rotate logs: Max 5MB, keep 3 backup files (Retained Logic)
        handler = RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3)
        formatter = logging.Formatter('%(asctime)s - [%(levelname)s] - %(message)s')
        handler.setFormatter(formatter)

        self.logger = logging.getLogger("TitanBot")
        self.logger.setLevel(logging.INFO)
        
        # Check if handler exists to avoid duplication on re-init
        if not self.logger.handlers:
            self.logger.addHandler(handler)
        
        # Note: Console output is handled by main SystemController prints or specific event prints, 
        # avoiding double-print here.

    def log_event(self, type, module, msg, payload=None):
        """
        Records an event to both Disk (Logfile) and SQLite (DB).
        OPTIMIZED: No file-open overhead per call.
        """
        # 1. Write to Text File
        full_msg = f"[{type}] [{module}] {msg}"
        self.logger.info(full_msg) 
        
        # 2. Write to DB (Persistent Connection)
        if self.conn:
            try:
                data = json.dumps(payload) if payload else "{}"
                self.conn.execute(
                    "INSERT INTO audit_log (event_type, module, message, payload) VALUES (?, ?, ?, ?)",
                    (type, module, msg, data)
                )
                self.conn.commit()
            except sqlite3.Error as e:
                # Silent fail safety - don't crash the trading bot because logs failed
                # print(f"Audit Write Fail: {e}") 
                pass

    def close(self):
        """Graceful shutdown."""
        if self.conn:
            self.conn.close()

    def __del__(self):
        """Destructor safeguard."""
        try:
            if hasattr(self, 'conn') and self.conn:
                self.conn.close()
        except: pass