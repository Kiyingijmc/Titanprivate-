# ==============================================================================
# FILE: src/ops/telemetry.py
# TYPE: RELIABILITY UPDATE (Network & Logging)
# AUDIT: 
#   1. Implemented TCP Connection Pooling (requests.Session).
#   2. Added Retry Logic with Backoff for message delivery.
#   3. Replaced silent failures with Audit Logging.
# STATUS: PRODUCTION READY
# ==============================================================================

import requests
import asyncio
import os
import time
from dotenv import load_dotenv

class TelegramBot:
    """
    Titan Institutional Telemetry Interface.
    
    AUDIT UPGRADE:
    - Persistent HTTP Session (Reuse SSL Handshakes).
    - Retry mechanism for dropped packets.
    - Error logging instead of silent failure.
    """
    
    # Stylized Institutional Menu
    HELP_MENU = (
        "🤖 *TITAN SMC COMMANDER v14.3*\n"
        "➖➖➖➖➖➖➖➖\n"
        "📊 `/status`   - Strategy Dashboard\n"
        "💰 `/balance`  - Account Equity\n"
        "📋 `/pending`  - **View Pending Orders**\n"
        "🛑 `/pause`    - **Freeze Execution**\n"
        "▶️ `/resume`   - **Resume Trading**\n"
        "🗑️ `/cancel ID`- Cancel Pending Order\n"
        "✂️ `/close ID` - **Close Active Trade**\n"
        "☠️ `/closeall` - **CLOSE ALL MARKET POSITIONS**\n"
        "🚨 `/panic`    - **EMERGENCY FLATTEN**"
    )

    def __init__(self, logger):
        self.logger = logger
        load_dotenv()
        
        self.token = os.getenv("TELEGRAM_TOKEN")
        self.allowed_chat_id = os.getenv("TELEGRAM_CHAT_ID")
        self.base_url = f"https://api.telegram.org/bot{self.token}"
        
        # AUDIT FIX: Persistent Session for Keep-Alive
        self.session = requests.Session()
        self.session.headers.update({"Connection": "keep-alive"})
        
        self.last_update_id = 0
        self.controller_ref = None
        self.last_poll = 0
        self.is_active = bool(self.token) and self.token != "x"

        if not self.is_active:
            self.logger.log_event("WARN", "TELEMETRY", "Telegram Token invalid. Telemetry Disabled.")

    def register_controller(self, controller):
        self.controller_ref = controller

    # --- 1. SIGNAL ALERT (SMC FORMAT) ---
    async def notify_signal(self, symbol, strategy, side, size, price, sl, tp):
        """Called when Python sends the order to MT5"""
        icon = "🟢" if "BUY" in side else "🔴"
        
        msg = (
            f"📨 *SMC SIGNAL GENERATED*\n"
            f"➖➖➖➖➖➖➖➖\n"
            f"🧠 **Model:** `{strategy}`\n"
            f"{icon} **{symbol}** {side}\n"
            f"⚖️ **Size:** `{size} Lots`\n"
            f"📍 **Entry:** `{price}`\n"
            f"🛡️ **SL:** `{sl}`\n"
            f"🎯 **TP:** `{tp}`"
        )
        await self.send_message(msg)

    # --- 2. EXECUTION CONFIRMATION ---
    async def notify_execution(self, ticket, symbol, type, price, sl, strategy):
        """Called when MT5 confirms open"""
        msg = (
            f"⚡ *EXECUTION CONFIRMED*\n"
            f"➖➖➖➖➖➖➖➖\n"
            f"🎫 **Ticket:** `#{ticket}`\n"
            f"💱 **Pair:** {symbol}\n"
            f"🕹️ **Type:** {type}\n"
            f"⚙️ **Logic:** _{strategy}_"
        )
        await self.send_message(msg)

    # --- 3. CLOSE ALERT (PNL REACTION) ---
    async def notify_close(self, ticket, pnl, symbol="???", strategy="Unknown"):
        """Called when a trade closes. Includes Strategy Name."""
        pnl = float(pnl)
        
        # Dynamic Icons for PnL impact
        if pnl > 500: icon = "🚀🔥" 
        elif pnl > 0: icon = "💰"    
        elif pnl > -50: icon = "📉"  
        else: icon = "🩸"            
        
        msg = (
            f"{icon} *POSITION CLOSED*\n"
            f"➖➖➖➖➖➖➖➖\n"
            f"🎫 `#{ticket}` **{symbol}**\n"
            f"🧠 Strat: `{strategy}`\n"
            f"💵 **PnL:** `${pnl:,.2f}`"
        )
        await self.send_message(msg)

    # --- 4. RATCHET MANAGEMENT ---
    async def notify_management(self, action_comment, ticket):
        icon = "⚙️"
        desc = action_comment
        
        if "L1" in action_comment:
            icon = "🔒"
            desc = "Ratchet L1 (Break-Even)"
        elif "L2" in action_comment:
            icon = "💸"
            desc = "Ratchet L2 (Bank 30%)"
        elif "L3" in action_comment:
            icon = "🥂"
            desc = "Ratchet L3 (Bank 50%)"
        elif "Risk" in action_comment:
            icon = "👮"
            desc = "**RISK GUARD KILL**"
        
        msg = f"{icon} **Auto-Pilot:** {desc}\n🎫 Trade `#{ticket}`"
        await self.send_message(msg)

    # --- CORE NETWORK LAYER ---
    async def send_message(self, text):
        if not self.is_active: return
        # Dispatch to async thread worker
        asyncio.create_task(self._async_send_retry(text))

    async def _async_send_retry(self, text, retries=3):
        """
        Sends message with Exponential Backoff Retry.
        Prevents lost alerts during minor network hiccups.
        """
        payload = {"chat_id": self.allowed_chat_id, "text": text, "parse_mode": "Markdown"}
        
        for attempt in range(retries):
            try:
                await asyncio.to_thread(
                    self.session.post, 
                    f"{self.base_url}/sendMessage", 
                    json=payload, 
                    timeout=5
                )
                return # Success
            except requests.RequestException as e:
                if attempt == retries - 1:
                    # Log final failure to system audit
                    self.logger.log_event("ERROR", "TELEMETRY", f"Failed to send: {e}")
                else:
                    # Backoff: 0.5s, 1.0s, etc.
                    await asyncio.sleep(0.5 * (2 ** attempt))

    async def poll_commands(self):
        """
        Long Polling for incoming Admin commands.
        """
        if not self.is_active: return
        
        # Poll throttling (2.0s interval)
        if time.time() - self.last_poll < 2.0: return
        self.last_poll = time.time()

        try:
            payload = {"offset": self.last_update_id + 1, "timeout": 1}
            resp = await asyncio.to_thread(
                self.session.post, 
                f"{self.base_url}/getUpdates", 
                json=payload, 
                timeout=3
            )
            
            if resp.status_code == 200:
                data = resp.json()
                if data.get("ok"):
                    for u in data.get("result", []):
                        self.last_update_id = u["update_id"]
                        asyncio.create_task(self._process(u))
                        
        except requests.RequestException:
            # Silent fail on poll is fine, we just miss a poll cycle
            pass

    async def _process(self, update):
        """Processes a single update safely."""
        try:
            msg = update.get("message", {})
            
            # Auth Check
            sender_id = str(msg.get("from", {}).get("id"))
            if sender_id != str(self.allowed_chat_id): 
                return
            
            text = msg.get("text", "").lower().strip()
            print(f"[CMD] {text}")
            
            if not self.controller_ref: return
            
            # --- COMMAND PARSING ---
            if "/status" in text: 
                await self.send_message(self.controller_ref.get_status_report())
            
            elif "/balance" in text: 
                await self.send_message(self.controller_ref.get_balance_report())
            
            elif "/pending" in text:
                await self.send_message(self.controller_ref.get_pending_orders_report())
                
            elif "/pause" in text: 
                await self.send_message(f"⏸️ System: {self.controller_ref.set_system_pause(True)}")
            
            elif "/resume" in text: 
                await self.send_message(f"▶️ System: {self.controller_ref.set_system_pause(False)}")
            
            elif "/cancel" in text:
                try:
                    args = text.split()
                    if len(args) < 2:
                        await self.send_message("⚠️ Usage: `/cancel 123456` or `/cancel all`")
                    else:
                        target = args[1] if "all" not in args[1] else None
                        res = await self.controller_ref.cancel_pending_orders(target)
                        await self.send_message(f"🗑️ Result: {res}")
                except Exception as e:
                    await self.send_message(f"❌ Error: {e}")

            elif "/close" in text and "/closeall" not in text:
                try:
                    args = text.split()
                    if len(args) < 2:
                        await self.send_message("⚠️ Usage: `/close 123456` (Active Ticket ID)")
                    else:
                        target_id = int(args[1])
                        res = await self.controller_ref.close_specific_market_order(target_id)
                        await self.send_message(res)
                except Exception as e:
                    await self.send_message(f"❌ Error: {e}")

            elif "/closeall" in text:
                res = await self.controller_ref.close_all_market_orders()
                await self.send_message(f"☠️ **GLOBAL CLOSE:** `{res}` positions flattened.")

            elif "/panic" in text:
                await self.controller_ref.trigger_panic()
                await self.send_message("🚨 **PANIC PROTOCOL EXECUTED** 🚨")
                
            else:
                await self.send_message(self.HELP_MENU)
                
        except Exception as e:
            self.logger.log_event("ERROR", "TELEMETRY", f"Cmd Process Fail: {e}")