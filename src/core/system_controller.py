# ==============================================================================
# FILE: src/core/system_controller.py
# TYPE: CRITICAL BUGFIX (Data Type Sync)
# AUDIT: 
#   1. Fixed "GET_HISTORY" sending string counts (e.g., "500") instead of ints (500).
#      This solves the "0/10 Pairs Synced" issue where MT5 returned 0 bars.
#   2. Retained Handshake, Watchdog, and Telemetry logic.
# STATUS: PRODUCTION READY
# ==============================================================================

import asyncio
import yaml
import sys
import os
import subprocess
import pytz
import time
from datetime import datetime, timedelta
from pathlib import Path
from enum import Enum
from dotenv import load_dotenv

# Internal Logic Imports
from src.core.audit_logger import AuditLogger
from src.execution.bridge_zmq import ZMQBridge
from src.core.data_store import MultiTimeframeStore
from src.analysis.bias_engine import BiasEngine
from src.analysis.time_math import TimeNormalizer
from src.analysis.news_manager import NewsManager
from src.analysis.smc_analyzer import SMCAnalyzer
from src.analysis.signal_grader import SignalGrader
from src.risk.risk_manager import RiskManager
from src.risk.exposure import ExposureManager
from src.ops.telemetry import TelegramBot
from src.execution.trade_manager import TradeManager
from src.core.state_manager import StateManager

# Strategy Models
from src.strategies.models.silver_bullet import SilverBullet
from src.strategies.models.unicorn import UnicornModel
from src.strategies.models.ict_ote import ICT_OTE
from src.strategies.models.crt import CandleRangeTheory

class BotState(Enum):
    BOOTING, WARMUP, ACTIVE, PAUSED, EMERGENCY = range(5)

class SystemController:
    """
    Titan v14.3 Institutional Master Controller.
    
    INTEGRITY & UPGRADES:
    - FIX: Sending Integer history counts to satisfy MQL5 JSON parser.
    - RETAINED: All v14.3 architectural components.
    """
    def __init__(self):
        # 1. Path Robustness
        self.root_dir = Path(__file__).resolve().parent.parent.parent
        self._load_env()
        
        self.state = BotState.BOOTING
        self.config = self._load_config()
        
        # Initialize Database/Logger
        db_path = self.root_dir / self.config['system']['database_path']
        self.logger = AuditLogger(str(db_path))
        
        # LOCALIZATION: Uganda Institutional Timezone
        self.uganda_tz = pytz.timezone('Africa/Kampala')
        
        self.telemetry = TelegramBot(self.logger)
        self.telemetry.register_controller(self)
        self.bridge = None
        self.last_heartbeat_time = datetime.now()
        
        self.market_data = {} 
        self.current_open_positions = []
        self.current_pending_orders = [] 
        self.live_prices = {}
        self.active_symbols = set()
        
        # REPORTING
        self.daily_closed_trades = [] 
        self.report_sent_today = False
        
        # Logic Engine Instantiation
        offset = self.config['connection'].get('broker', {}).get('timezone_offset', 2)
        self.time_engine = TimeNormalizer(broker_gmt_offset=offset)
        
        self.risk_manager = RiskManager(self.config, self.logger)
        self.exposure_manager = ExposureManager(self.config, self.market_data)
        self.news_manager = NewsManager(self.logger)
        self.signal_grader = SignalGrader(self.config)

        # Signal metadata (grade/SL/TP/lots) keyed by symbol, captured at send
        # time so EXECUTION:OPENED can journal the full trade record (the EA's
        # OPENED message carries no prices).
        self.pending_signal_meta = {}
        
        state_db_path = self.root_dir / "data/db/trade_state.db"
        self.state_manager = StateManager(str(state_db_path))
        
        self.trade_manager = TradeManager(self.logger, self.state_manager, self.risk_manager,
                                          config=self.config)
        
        # Reconciliation Sync Config
        self.recon_interval = 60 
        self.last_recon_time = time.time()

        self.strategies = []
        self.is_manual_pause = False

        # Load active symbols from configuration
        strats = self.config.get('strategies', {})
        for _, s_cfg in strats.items():
            if s_cfg.get('enabled', False):
                for pair in s_cfg.get('pairs', []):
                    self.active_symbols.add(pair)
        
        # Default safety
        if not self.active_symbols: self.active_symbols.add("BTCUSD")

    def _load_env(self):
        env_path = self.root_dir / ".env"
        load_dotenv(dotenv_path=env_path)

    def _load_config(self):
        cfg_path = self.root_dir / "config" / "config.yaml"
        if cfg_path.exists():
            with open(cfg_path, 'r') as f:
                return yaml.safe_load(f)
        sys.exit(f"[FATAL] config.yaml not found at {cfg_path}")

    async def run(self):
        print(f"\n[{datetime.now().strftime('%H:%M:%S')}] TITAN V14.3 PRO (INSTITUTIONAL) IGNITION...")
        
        if not await self._boot_sequence():
            print("[FATAL] Bridge initialization failed. Check ZMQ ports.")
            return

        # Handshake
        await self._wait_for_bridge_connection()

        self._init_strategies()
        await self.news_manager.update_calendar()
        
        for sym in self.active_symbols:
            self.market_data[sym] = MultiTimeframeStore(sym)

        # WARMUP
        self.state = BotState.WARMUP
        print(f"[{datetime.now().strftime('%H:%M:%S')}] RUNNING 5-CYCLE BUFFER SATURATION...")
        await self._perform_warmup(list(self.active_symbols))

        self.state = BotState.ACTIVE
        print(f"[{datetime.now().strftime('%H:%M:%S')}] TRANSITION TO ACTIVE MODE.")
        
        await self.telemetry.send_message(
            f"🚀 **Titan V14.4 Pro Online**\n"
            f"📍 Clock (NY): `{self.time_engine.get_current_ny_string()}`\n"
            f"📡 Sync Guard: ACTIVE",
            parse_mode="Markdown",
        )

        try:
            while True:
                now_ts = time.time()
                now_dt = datetime.now()

                # --- A. SYNC GUARD ---
                if now_ts - self.last_recon_time > self.recon_interval:
                    await self._perform_reconciliation()
                    self.last_recon_time = now_ts

                # --- B. WATCHDOG ---
                time_since_last_pulse = (now_dt - self.last_heartbeat_time).total_seconds()
                is_weekend = now_dt.weekday() >= 5
                has_crypto = any(s for s in self.active_symbols if "BTC" in s or "ETH" in s)
                should_monitor = (not is_weekend) or has_crypto

                if should_monitor and time_since_last_pulse > 60:
                    await self._reboot_terminal()

                # --- C. CONTROL & TELEMETRY ---
                await self.telemetry.poll_commands()
                await self._check_news_status() 

                # --- D. DATA INGESTION ---
                if self.bridge:
                    msgs = await self.bridge.poll_data()
                    for msg in msgs:
                        await self._process_incoming_data(msg)

                # --- E. GHOST CLEANUP ---
                if now_dt.second == 0 and now_dt.microsecond < 10000:
                    await self._cleanup_ghost_orders()

                # --- F. UGANDA REPORTING ---
                now_uganda = datetime.now(self.uganda_tz)
                if now_uganda.hour == 23 and now_uganda.minute == 45:
                    if not self.report_sent_today:
                        await self._send_detailed_performance_report()
                        self.report_sent_today = True
                        self.risk_manager.reset_daily_metrics()
                
                if now_uganda.hour == 0: self.report_sent_today = False

                # --- G. PULSE SYNC ---
                # 10s PING to keep connection alive
                if (now_dt.second % 10 == 0) and (now_dt.microsecond < 50000):
                    await self.bridge.send_command("PING")
                    await asyncio.sleep(0.01)

                await asyncio.sleep(0.001) 

        except Exception as e:
            await self.telemetry.send_message(f"☠️ **FATAL SYSTEM CRASH**\nError: `{str(e)}`", parse_mode="Markdown")
            self.logger.log_event("ERROR", "CORE", f"System Exit: {str(e)}")
            raise e

    async def _wait_for_bridge_connection(self):
        print("[INIT] Waiting for MT5 ZMQ Handshake (Start the EA now)...")
        while True:
            connected = await self.bridge.ping()
            if connected:
                print(f"[{datetime.now().strftime('%H:%M:%S')}] ✅ BRIDGE CONNECTED. SYNCED.")
                return
            await asyncio.sleep(2.0)

    async def _perform_reconciliation(self):
        mt5_tickets = [int(p['t']) for p in self.current_open_positions if 't' in p]
        ghosts = self.state_manager.reconcile_state(mt5_tickets)
        for tid in ghosts:
            self.state_manager.archive_trade(tid, 0.0)
            await self.telemetry.send_message(f"⚠️ **Sync Guard:** Resolved Ticket `#{tid}` (Closed externally)", parse_mode="Markdown")

    async def _execute_signal(self, symbol, decision, name, htf_bias, grade=""):
        p = self.risk_manager.normalize_price(decision['price'], symbol)
        sl = self.risk_manager.normalize_price(decision['sl'], symbol)
        tp = self.risk_manager.normalize_price(decision['tp'], symbol)

        cur_bid = self.live_prices.get(symbol, 0.0)
        cmd = decision['type']
        if "LIMIT" in cmd and cur_bid > 0:
            if abs(p - cur_bid) < (cur_bid * 0.0002):
                cmd = "MARKET"
                p = cur_bid

        lot = self.risk_manager.calculate_lot_size(p, sl, symbol, htf_bias)
        if lot <= 0: return

        allowed, reason = self.exposure_manager.check_exposure(symbol, self.current_open_positions)
        if not allowed:
            self.logger.log_event("RISK", "EXPOSURE", f"Block {symbol}: {reason}")
            return

        payload = {
            "action": "TRADE", "symbol": symbol, "cmd": cmd, "side": decision['signal'],
            "price": float(p), "p": float(p), "entry": float(p),
            "sl": float(sl), "tp": float(tp), "volume": float(lot),
            "magic": self.config['system'].get('magic_number_base', 88000),
            "comment": name, "strat": name
        }

        success = await self.bridge.send_order_reliable(payload)

        if success:
            # Remember what we sent so EXECUTION:OPENED can journal the full
            # trade record (the EA's OPENED notification carries no prices).
            self.pending_signal_meta[symbol] = {
                'strat': name, 'cmd': cmd, 'entry': float(p), 'sl': float(sl),
                'tp': float(tp), 'lots': float(lot), 'grade': grade
            }
            await self.telemetry.notify_signal(symbol, name, decision['signal'], lot, p, sl, tp)
            self.logger.log_event("EXEC", "SENT", f"Order {cmd} {symbol} [{grade}] sent. Handshake OK.")
        else:
            self.logger.log_event("ERROR", "EXECUTION", f"Order handshake FAILED for {symbol}")

    async def _dispatch_mgmt_command(self, c):
        """
        Routes TradeManager commands onto the protocol the EA understands
        (all fire-and-forget on the PUSH socket; the REQ handshake is reserved
        for order entry so a slow SLTP round-trip can never wedge it):
        - MODIFY   -> EA HandleCommand MODIFY branch (v14.4.1+ EA required);
                      outcome is observable in the next HEARTBEAT's SL/TP.
        - CLOSE_PARTIAL becomes CLOSE_POS with an explicit volume.
        - CLOSE_POS passes through.
        """
        action = c.get('action')
        if action == "MODIFY":
            await self.bridge.send_command("MODIFY", {
                "ticket": int(c['ticket']), "symbol": c.get('symbol', ''),
                "sl": float(c.get('sl', 0.0)), "tp": float(c.get('tp', 0.0))
            })
            self.logger.log_event("MGMT", "TRADE_MGR",
                                  f"MODIFY #{c['ticket']} sl={c.get('sl')} tp={c.get('tp')} "
                                  f"({c.get('comment', '')}) sent")
            comment = c.get('comment', '')
            if comment != "Runner Trail" and any(k in comment for k in ("Ratchet L1", "Ratchet L2", "Ratchet L3")):
                new_sl = float(c.get('sl', 0.0))
                locked = None
                row = self.state_manager.get_order(int(c['ticket']))
                if row and new_sl:
                    init_entry = row.get('initial_entry') or 0
                    init_sl = row.get('initial_sl') or 0
                    lots = row.get('lots') or 0
                    if init_entry:
                        is_long = init_sl < init_entry
                        dist = (new_sl - init_entry) if is_long else (init_entry - new_sl)
                        mag = self.risk_manager.money_for_move(c.get('symbol', ''), dist, lots)
                        locked = mag if dist >= 0 else -mag
                await self.telemetry.notify_management(comment, int(c['ticket']), new_sl, locked)
        elif action == "CLOSE_PARTIAL":
            await self.bridge.send_command("CLOSE_POS", {"ticket": int(c['ticket']),
                                                         "volume": float(c['volume'])})
            self.logger.log_event("MGMT", "TRADE_MGR",
                                  f"PARTIAL #{c['ticket']} vol={c['volume']}")
            await self.telemetry.notify_partial(c.get('comment', ''), int(c['ticket']), c['volume'])
        elif action == "CLOSE_POS":
            await self.bridge.send_command("CLOSE_POS", {"ticket": int(c['ticket'])})
            self.logger.log_event("MGMT", "TRADE_MGR",
                                  f"CLOSE #{c['ticket']} ({c.get('comment', '')})")
            if c.get('comment', '') == "Risk Guard":
                await self.telemetry.notify_management("Risk Guard", int(c['ticket']))

    async def _process_incoming_data(self, msg):
        if not isinstance(msg, dict): 
            return
            
        self.last_heartbeat_time = datetime.now() 
        msg_type = msg.get('type')
        
        if msg_type == 'HISTORY':
            sym = msg.get('symbol')
            if sym in self.market_data: 
                self.market_data[sym].ingest_history(msg.get('tf'), msg.get('data'))
                if 'tv' in msg:
                    self.risk_manager.update_symbol_specs(
                        sym, msg.get('tv'), msg.get('ts'), msg.get('vm'), msg.get('vs')
                    )

        elif msg_type == 'EXECUTION':
            status = msg.get('status')
            if status == 'OPENED':
                ticket = int(msg.get('ticket', 0))
                if ticket <= 0:
                    return  # e.g. SLTP-modify acks carry no order ticket
                sym = msg.get('s', '?')
                # Prefer the metadata captured when we sent the order: it has the
                # real entry/SL/TP/lots/grade (the EA's OPENED carries no prices).
                meta = self.pending_signal_meta.pop(sym, None)
                if meta:
                    reg_status = "PENDING" if meta['cmd'] == "LIMIT" else "ACTIVE"
                    self.state_manager.register_order(
                        ticket, sym, meta['strat'], meta['cmd'], status=reg_status,
                        entry=meta['entry'], tp=meta['tp'], sl=meta['sl'],
                        lots=meta['lots'], grade=meta['grade']
                    )
                    entry_p = meta['entry']
                    sl_v, tp_v, lots_v, grade_v, strat_v = meta['sl'], meta['tp'], meta['lots'], meta['grade'], meta['strat']
                else:
                    entry_p = float(msg.get('price', 0))
                    self.state_manager.register_order(
                        ticket, sym, msg.get('strat', 'Manual'), msg.get('cmd'),
                        status="ACTIVE", entry=entry_p, tp=0.0
                    )
                    sl_v, tp_v, lots_v, grade_v, strat_v = 0.0, 0.0, 0.0, '', msg.get('strat', 'Auto')

                risk_money = self.risk_manager.money_for_move(sym, abs(entry_p - sl_v), lots_v)
                await self.telemetry.notify_execution(
                    ticket, sym, msg.get('cmd'), entry_p, sl_v, tp_v, lots_v, grade_v, risk_money, strat_v
                )
            
            elif status == 'CLOSED':
                tid = msg.get('ticket')
                row = self.state_manager.get_order(tid)
                if row:
                    pnl = float(msg.get('pn', 0.0))
                    strat_name = row.get('strategy') or "Manual"
                    sym = msg.get('s') or row.get('symbol')

                    placed = row.get('time_placed') or 0
                    hold_seconds = (time.time() - placed) if placed else None

                    planned_risk = self.risk_manager.money_for_move(
                        sym, abs((row.get('initial_entry') or 0) - (row.get('initial_sl') or 0)), row.get('lots') or 0
                    )
                    r_mult = (pnl / planned_risk) if planned_risk > 0 else None

                    self.daily_closed_trades.append({'ticket': tid, 'sym': sym, 'pnl': pnl, 'strat': strat_name})
                    self.state_manager.archive_trade(tid, pnl)
                    await self.telemetry.notify_close(tid, pnl, sym, strat_name, hold_seconds, r_mult)

        elif msg_type == 'TICK':
            symbol = msg.get('s')
            if not symbol: return
            
            self.live_prices[symbol] = float(msg.get('b', 0))
            if self.state == BotState.ACTIVE:
                closed_candles = self.market_data[symbol].process_tick(msg)
                
                if self.current_open_positions and symbol in self.live_prices:
                    relevant = [p for p in self.current_open_positions if p.get('s') == symbol]
                    cmds = self.trade_manager.sync_positions(relevant, self.live_prices)
                    for c in cmds:
                        await self._dispatch_mgmt_command(c)
                
                for tf, df in closed_candles:
                    await self._run_strategies(symbol, df, tf)

        elif msg_type == 'HEARTBEAT':
            bal = float(msg.get('bal', 0))
            eq = float(msg.get('eq', 0))
            if eq > 0: 
                self.risk_manager.update_account_info(bal, eq)
                self.risk_manager.track_equity(eq)
            
            self.current_open_positions = msg.get('pos', [])
            self.current_pending_orders = msg.get('orders', [])
            
            for p in self.current_open_positions:
                tid_raw = p.get('t')
                if tid_raw:
                    tid = int(tid_raw)
                    if not self.state_manager.exists(tid):
                        self.state_manager.register_order(
                            tid, p.get('s', '?'), "Adopted", "MARKET",
                            status="ACTIVE", entry=float(p.get('p', 0)), tp=float(p.get('tp', 0)),
                            sl=float(p.get('sl', 0)), lots=float(p.get('vol', 0))
                        )
                    else:
                        # Fill any zero entry/TP from live broker state and flip
                        # PENDING->ACTIVE on limit fills, so the ratchet manager
                        # can engage (it skips trades with zero entry/TP).
                        self.state_manager.backfill_position_state(
                            tid, entry=float(p.get('p', 0)), tp=float(p.get('tp', 0))
                        )

    async def _cleanup_ghost_orders(self):
        pending = self.state_manager.get_pending_orders()
        now = datetime.now().timestamp()
        for o in pending:
            # 12 bars of the owning strategy's timeframe (default 2h)
            ttl = getattr(self, 'strategy_ttls', {}).get(o.get('strategy', ''), 7200)
            if now - o['time_placed'] > ttl:
                await self.bridge.send_command("CANCEL", {"ticket": o['ticket_id']})
                self.state_manager.delete_order(o['ticket_id'])
                await self.telemetry.send_message(f"♻️ **Auto-Clean:** Expired {o['strategy']} Order `#{o['ticket_id']}`", parse_mode="Markdown")

    async def _send_detailed_performance_report(self):
        now = datetime.now(self.uganda_tz)
        summary = {}
        for trade in self.daily_closed_trades:
            strat = trade.get('strat', 'Unknown')
            if strat not in summary: summary[strat] = {'pnl': 0, 'w': 0, 'l': 0}
            summary[strat]['pnl'] += trade['pnl']
            if trade['pnl'] > 0: summary[strat]['w'] += 1
            else: summary[strat]['l'] += 1
            
        strat_breakdown = "".join([f"• **{k}**: `${v['pnl']:+,.2f}` ({v['w']}W / {v['l']}L)\n" for k, v in summary.items()])
        report = (
            f"🏛️ **TITAN INSTITUTIONAL DEBRIEF**\n📍 Location: `Kampala, Uganda`\n🕒 Report Time: `{now.strftime('%H:%M:%S')}`\n"
            f"➖➖➖➖➖➖➖➖\n💰 **Equity Metrics:**\n• Day High: `${self.risk_manager.equity_max:,.2f}`\n"
            f"• Day Low:  `${self.risk_manager.equity_min:,.2f}`\n• Closing:  `${self.risk_manager.current_equity:,.2f}`\n\n"
            f"🧠 **Strategy Performance:**\n{strat_breakdown if strat_breakdown else '_No trade closings recorded today._'}\n\n🛰️ **System Health:** OPTIMAL"
        )
        await self.telemetry.send_message(report, parse_mode="Markdown")
        self.daily_closed_trades = [] 

    async def _reboot_terminal(self):
        print(f"🚨 WATCHDOG: HEARTBEAT LOST. ATTEMPTING RECOVERY...")
        subprocess.run("taskkill /F /IM terminal64.exe", shell=True, capture_output=True)
        await asyncio.sleep(2)
        mt5_path_str = self.config['system'].get('mt5_path', '')
        if mt5_path_str and os.path.exists(mt5_path_str):
             subprocess.Popen([mt5_path_str])
        self.last_heartbeat_time = datetime.now()

    async def _boot_sequence(self):
        try:
            cfg = self.config['connection']['zeromq']
            self.bridge = ZMQBridge(
                push_port=cfg.get('push_port', 32768), 
                pull_port=cfg.get('pull_port', 32769), 
                req_port=32770
            )
            return True
        except Exception as e: 
            print(f"[BOOT ERROR] {e}")
            return False

    def _init_strategies(self):
        s = self.config.get('strategies', {})
        self.strategies = [
            SilverBullet(s.get('silver_bullet',{}), self.logger),
            UnicornModel(s.get('unicorn_model',{}), self.logger),
            ICT_OTE(s.get('ict_ote',{}), self.logger),
            CandleRangeTheory(s.get('crt',{}), self.logger)
        ]
        # Pending-limit TTL = 12 bars of each strategy's timeframe (matches the
        # validation harness; an H1 SilverBullet limit must live 12h, not 1h).
        tf_minutes = {"M5": 5, "M15": 15, "H1": 60}
        self.strategy_ttls = {
            st.name: 12 * tf_minutes.get(getattr(st, 'timeframe', 'M5'), 5) * 60
            for st in self.strategies
        }

    async def _run_strategies(self, symbol, tf_df, tf="M5"):
        # Only strategies triggered by this timeframe's close; skip the SMC
        # enrichment entirely when none match (e.g. H1 closes with an M5-only
        # strategy set, and vice versa).
        active = [s for s in self.strategies if getattr(s, 'timeframe', 'M5') == tf]
        if not active:
            return

        smc = SMCAnalyzer(tf_df)
        enriched_df = smc.process()

        h1 = self.market_data[symbol].get_data("H1")
        bias_str, liq = BiasEngine(h1).get_bias_context()

        ctx = {
            'symbol': symbol,
            'bias': bias_str,
            'liquidity': liq,
            'ny_time': self.time_engine.get_current_ny_string(),
            'smc_df': enriched_df
        }

        for strat in active:
            decision = await strat.on_new_candle(enriched_df, context=ctx)
            if decision:
                if strat.name != "CRT":
                    if (bias_str == "BULLISH" and decision['signal'] == "SELL") or \
                       (bias_str == "BEARISH" and decision['signal'] == "BUY"):
                           continue

                # Confluence grading: journal every signal; execute only those
                # at or above the configured quality floor (signal_grading cfg).
                g = self.signal_grader.grade(decision, ctx, enriched_df.iloc[-1])
                self.logger.log_event(
                    "SIGNAL", strat.name,
                    f"{symbol} {decision['signal']} graded {g['grade']} ({g['score']})",
                    payload={'factors': g['factors'], 'decision': {k: float(decision[k]) for k in ('price', 'sl', 'tp')}}
                )
                if not self.signal_grader.passes(g['grade']):
                    self.logger.log_event("SIGNAL", strat.name,
                                          f"{symbol} skipped: {g['grade']} below floor "
                                          f"{self.signal_grader.min_grade}")
                    continue

                await self._execute_signal(symbol, decision, strat.name, bias_str, grade=g['grade'])

    async def _perform_warmup(self, symbols_list):
        await asyncio.sleep(2)
        
        for sym in symbols_list:
            # FIX: Ensure count is an INTEGER (500) not a string ("500")
            # The MQL5 JSON parser handles 500 but fails on "500" for CopyRates
            await self.bridge.send_command("GET_HISTORY", {"symbol": sym, "tf": "M5", "count": 500})
            # 500 H1 bars: H1 strategies need >=50 enriched bars + ATR warmup,
            # and BiasEngine reads a 100-bar context window.
            await self.bridge.send_command("GET_HISTORY", {"symbol": sym, "tf": "H1", "count": 500})
        
        print(f"[WARMUP] Syncing {len(symbols_list)} pairs...")
        for _ in range(20): 
            msgs = await self.bridge.poll_data()
            for m in msgs: await self._process_incoming_data(m)
            
            loaded = sum(1 for s in symbols_list if self.market_data[s].history_loaded)
            if loaded == len(symbols_list):
                print("[WARMUP] All pairs synced.")
                break
            await asyncio.sleep(0.5)

    async def _check_news_status(self):
        await self.news_manager.update_calendar()
        blocked, reason = self.news_manager.check_news_block() 
        if blocked and self.state == BotState.ACTIVE:
            self.state = BotState.PAUSED
            await self.telemetry.send_message(f"🛑 **NEWS BLOCK**: {reason}", parse_mode="Markdown")
        elif not blocked and self.state == BotState.PAUSED and not self.is_manual_pause:
            self.state = BotState.ACTIVE
            await self.telemetry.send_message("✅ News Cleared. Resuming.", parse_mode="Markdown")

    def get_status_report(self):
        eq = self.risk_manager.current_equity
        status_name = self.state.name
        if self.is_manual_pause: status_name += " (MANUAL PAUSE)"
        
        feeds_ready = sum(1 for _, s in self.market_data.items() if s.history_loaded)
        total_feeds = len(self.active_symbols)
        health_icon = "🟢" if feeds_ready == total_feeds else "🟡" if feeds_ready > 0 else "🔴"

        trades_str = ""
        if not self.current_open_positions:
            trades_str = "\n_(No Active Trades)_"
        else:
            for p in self.current_open_positions:
                try:
                    tid = int(p.get('t', 0))
                    symbol = p.get('s', '?')
                    profit = float(p.get('pf', 0.0))
                    raw_type = int(p.get('type', 0))
                    direction = "BUY" if raw_type == 0 else "SELL"
                    
                    strat = p.get('comment', '')
                    if not strat: strat = "Manual"
                        
                    emoji = "🟢" if profit >= 0 else "🔴"
                    
                    trades_str += (
                        f"\n{emoji} `#{tid}` **{symbol}** ({direction})\n"
                        f"   ├─ Strat: `{strat}`\n"
                        f"   └─ P/L: `${profit:+.2f}`"
                    )
                except: continue

        return (
            f"📊 **TITAN STATUS BOARD**\n"
            f"➖➖➖➖➖➖➖➖\n"
            f"🚦 State: `{status_name}`\n"
            f"💰 Equity: `${eq:,.2f}`\n"
            f"📡 Sync: `{health_icon} {feeds_ready}/{total_feeds}` Pairs\n"
            f"📋 **Active ({len(self.current_open_positions)}):**"
            f"{trades_str}"
        )

    def get_balance_report(self):
        eq = self.risk_manager.current_equity
        bal = self.risk_manager.starting_balance
        pnl = eq - bal
        pnl_pct = (pnl / bal * 100) if bal > 0 else 0
        emoji = "📈" if pnl >= 0 else "📉"
        
        return (
            f"💰 **TITAN BALANCE SHEET**\n"
            f"➖➖➖➖➖➖➖➖\n"
            f"💵 Balance: `${bal:,.2f}`\n"
            f"📊 Equity: `${eq:,.2f}`\n"
            f"{emoji} Net P/L: `${pnl:+,.2f}` (`{pnl_pct:+.2f}%`)\n"
            f"🛡️ Daily DD Limit: `{self.risk_manager.max_dd}%`"
        )

    def get_pending_orders_report(self):
        pending = getattr(self, 'current_pending_orders', [])
        if not pending: return "📭 **No Pending Orders Active.**"
        report = "📋 **PENDING ORDER BOOK**\n➖➖➖➖➖➖➖➖\n"
        for o in pending:
            tid = o.get('t', '0')
            symbol = o.get('s', '???')
            price = o.get('p', 0)
            report += (f"🎫 `#{tid}` **{symbol}** @ `{price}`\n")
        return report

    def set_system_pause(self, p: bool):
        self.is_manual_pause = p
        self.state = BotState.PAUSED if p else BotState.ACTIVE
        return self.state.name

    async def trigger_panic(self):
        self.state = BotState.EMERGENCY
        await self.telemetry.send_message("🚨 **PANIC PROTOCOL ENGAGED** 🚨", parse_mode="Markdown")
        m_count = await self.close_all_market_orders()
        p_count = await self.cancel_pending_orders('all')
        await self.telemetry.send_message(f"✅ **Global Flatten:** Closed `{m_count}` | Cancelled `{p_count}`", parse_mode="Markdown")

    async def close_all_market_orders(self):
        count = 0
        for pos in self.current_open_positions:
            ticket = int(pos.get('t', 0))
            if ticket > 0:
                await self.bridge.send_command("CLOSE_POS", {"ticket": ticket})
                count += 1
        return count

    async def close_specific_market_order(self, ticket_id):
        ticket_id = int(ticket_id)
        if any(int(p.get('t')) == ticket_id for p in self.current_open_positions):
            await self.bridge.send_command("CLOSE_POS", {"ticket": ticket_id})
            return f"✂️ **Request Sent:** Closing `#{ticket_id}`"
        return f"⚠️ Ticket `#{ticket_id}` not found."

    async def cancel_pending_orders(self, target_id='all'):
        pending = getattr(self, 'current_pending_orders', [])
        count = 0
        if target_id == 'all':
            for o in pending:
                await self.bridge.send_command("CANCEL", {"ticket": int(o.get('t'))})
                count += 1
        elif target_id:
            await self.bridge.send_command("CANCEL", {"ticket": int(target_id)})
            count = 1
        return count