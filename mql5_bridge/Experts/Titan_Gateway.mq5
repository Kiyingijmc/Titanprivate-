//+------------------------------------------------------------------+
//|                                              Titan_Gateway.mq5 |
//|                                    Copyright 2026, Titan Algo   |
//|                              Version 14.3 Pro (Institutional)    |
//+------------------------------------------------------------------+
#property copyright "Copyright 2026, Titan Institutional"
#property version   "14.3"
#property strict

#include <TitanZmq.mqh>

//--- INPUTS
input string   InpIP          = "127.0.0.1"; 
input int      InpPullPort    = 32768; // Command Listener (MT5 PULL <- Py PUSH)
input int      InpPushPort    = 32769; // Data Streamer   (MT5 PUSH -> Py PULL)
input int      InpRepPort     = 32770; // Trade Handshake (MT5 REP  <-> Py REQ)
input int      InpTimerMS     = 10;    // Increased Frequency for High-Freq Trading
input long     InpMagic       = 88000;

//--- GLOBALS
TitanZmq       socket_pull, socket_push, socket_rep;
long           last_heartbeat = 0;
string         watchlist[];      
double         last_ask_prices[];
double         last_bid_prices[]; 

//+------------------------------------------------------------------+
int OnInit() {
   // ZMQ Architecture:
   // Python (Brain) BINDS ports. MT5 (Gateway) CONNECTS to them.
   if(!socket_pull.Init() || !socket_push.Init() || !socket_rep.Init()) return INIT_FAILED;
   
   if(!socket_pull.Connect(ZMQ_PULL, StringFormat("tcp://%s:%d", InpIP, InpPullPort))) return INIT_FAILED;
   if(!socket_push.Connect(ZMQ_PUSH, StringFormat("tcp://%s:%d", InpIP, InpPushPort))) return INIT_FAILED;
   if(!socket_rep.Connect(ZMQ_REP,   StringFormat("tcp://%s:%d", InpIP, InpRepPort)))  return INIT_FAILED;
   
   Print("TITAN v14.4 PRO | Institutional Gateway Online.");
   Print("Ports Configured: CMD:", InpPullPort, " | DATA:", InpPushPort, " | REP:", InpRepPort);
   
   EventSetMillisecondTimer(InpTimerMS);
   return INIT_SUCCEEDED;
}

void OnDeinit(const int reason) {
   EventKillTimer();
   socket_pull.Shutdown(); 
   socket_push.Shutdown(); 
   socket_rep.Shutdown();
}

void OnTimer() {
   // --- 1. REQ/REP HANDSHAKE (Highest Priority) ---
   string req_raw = socket_rep.Recv();
   if(req_raw != "") {
      
      // AUDIT FIX: PING INTERCEPTION
      if(StringFind(req_raw, "PING") >= 0) {
         // Immediate handshake reply for Python startup
         socket_rep.Send("{\"status\":\"OK\",\"type\":\"PONG\"}");
      }
      else {
         // It's a Trade Order
         Print("TITAN | REQ received: ", StringSubstr(req_raw, 0, 160));
         bool success = ExecuteTrade(req_raw);
         // Respond JSON so Python 'reliable_send' stops blocking.
         // v14.4.1: a failed reply wedges the REP state machine (it will
         // never Recv again) — log it loudly so it is visible in Experts.
         bool replied = socket_rep.Send(success ? "{\"status\":\"OK\"}" : "{\"status\":\"ERROR\"}");
         if(!replied) Print("TITAN | !! REP reply send FAILED — REP socket may be wedged, reattach EA");
      }
   }

   // --- 2. COMMAND LISTENER (Fire-and-forget) ---
   string cmd_raw = socket_pull.Recv();
   if(cmd_raw != "") HandleCommand(cmd_raw);

   // --- 3. TICK STREAMER ---
   int count = ArraySize(watchlist);
   if(ArraySize(last_bid_prices) != count) ArrayResize(last_bid_prices, count);
   if(ArraySize(last_ask_prices) != count) ArrayResize(last_ask_prices, count);

   for(int i=0; i<count; i++) {
      MqlTick t;
      if(SymbolInfoTick(watchlist[i], t)) {
         // Push only if price changes
         if(t.bid != last_bid_prices[i] || t.ask != last_ask_prices[i]) {
            // v14.4: full symbol precision (%G truncates to 6 sig figs and
            // drops cents on BTC/index prices)
            int dig = (int)SymbolInfoInteger(watchlist[i], SYMBOL_DIGITS);
            string msg = StringFormat("{\"type\":\"TICK\",\"s\":\"%s\",\"b\":%s,\"a\":%s,\"t\":%I64d}",
                                       watchlist[i], DoubleToString(t.bid, dig),
                                       DoubleToString(t.ask, dig), t.time_msc);
            socket_push.Send(msg);
            last_bid_prices[i] = t.bid;
            last_ask_prices[i] = t.ask;
         }
      }
   }

   // --- 4. HEARTBEAT SYNC ---
   if(GetTickCount64() - last_heartbeat > 5000) {
      SendHeartbeat();
      last_heartbeat = (long)GetTickCount64();
   }
}

//+------------------------------------------------------------------+
//| EXECUTION LOGIC                                                  |
//+------------------------------------------------------------------+
bool ExecuteTrade(string json) {
   MqlTradeRequest req; ZeroMemory(req); 
   MqlTradeResult res;  ZeroMemory(res);
   
   string sym = GetJSONString(json, "symbol");
   string side = GetJSONString(json, "side"); // BUY / SELL
   string cmd = GetJSONString(json, "cmd");   // MARKET / LIMIT
   
   if(sym == "") return false;

   req.magic = InpMagic; 
   req.symbol = sym; 
   req.volume = GetJSONDouble(json, "volume");
   req.sl = GetJSONDouble(json, "sl"); 
   req.tp = GetJSONDouble(json, "tp");
   req.comment = GetJSONString(json, "strat"); // Strategy Name
   req.deviation = 20;
   
   // AUDIT FIX: DYNAMIC FILLING MODE
   req.type_filling = GetFillingMode(sym);
   
   if(cmd == "MARKET") {
      req.action = TRADE_ACTION_DEAL;
      req.type = (side == "BUY") ? ORDER_TYPE_BUY : ORDER_TYPE_SELL;
      req.price = (side == "BUY") ? SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);
   } 
   else if(cmd == "LIMIT") {
      req.action = TRADE_ACTION_PENDING;
      req.type = (side == "BUY") ? ORDER_TYPE_BUY_LIMIT : ORDER_TYPE_SELL_LIMIT;
      req.price = GetJSONDouble(json, "price");
      req.expiration = 0; // GTC (Good Till Cancelled)
   }
   else if(cmd == "STOP") {
      // v14.4: Stop pending orders (breakout entries)
      req.action = TRADE_ACTION_PENDING;
      req.type = (side == "BUY") ? ORDER_TYPE_BUY_STOP : ORDER_TYPE_SELL_STOP;
      req.price = GetJSONDouble(json, "price");
      req.expiration = 0; // GTC (Good Till Cancelled)
   }
   else if(cmd == "MODIFY") {
      req.action = TRADE_ACTION_SLTP;
      req.position = (ulong)GetJSONLong(json, "ticket");
   }

   // Try Send
   if(OrderSend(req, res)) {
      if(res.retcode == TRADE_RETCODE_DONE || res.retcode == TRADE_RETCODE_PLACED) {
         // Notify Python via PUSH immediately.
         // v14.4: Only entry commands produce an OPENED event; an SLTP modify
         // has no order ticket and must not register a phantom trade.
         if(cmd != "MODIFY") {
            string notify = StringFormat("{\"type\":\"EXECUTION\",\"status\":\"OPENED\",\"ticket\":%I64d,\"s\":\"%s\",\"cmd\":\"%s\",\"strat\":\"%s\"}",
                                          (long)res.order, sym, side, req.comment);
            socket_push.Send(notify);
         }
         return true;
      }
      else {
         Print("TITAN | Execution Error: ", res.retcode, " Comment: ", res.comment);
      }
   }
   else {
      Print("TITAN | OrderSend Failed: ", GetLastError());
   }
   return false;
}

//+------------------------------------------------------------------+
//| STATE MANAGEMENT                                                 |
//+------------------------------------------------------------------+
void SendHeartbeat() {
   // 1. ACTIVE POSITIONS
   string pos_json = "[";
   int total = PositionsTotal();
   int added = 0;

   for(int i=0; i<total; i++) {
      ulong t_id = PositionGetTicket(i);
      if(PositionSelectByTicket(t_id)) {
         if(added > 0) pos_json += ",";

         // v14.4: DoubleToString at symbol digits (%G loses cents on BTC/indices)
         string p_sym = PositionGetString(POSITION_SYMBOL);
         int p_dig = (int)SymbolInfoInteger(p_sym, SYMBOL_DIGITS);

         // 'type' 0=BUY, 1=SELL in MT5
         pos_json += StringFormat(
            "{\"t\":%I64d,\"s\":\"%s\",\"p\":%s,\"sl\":%s,\"tp\":%s,\"pf\":%.2f,\"vol\":%.8f,\"type\":%d,\"comment\":\"%s\"}",
            (long)t_id,
            p_sym,
            DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), p_dig),
            DoubleToString(PositionGetDouble(POSITION_SL), p_dig),
            DoubleToString(PositionGetDouble(POSITION_TP), p_dig),
            PositionGetDouble(POSITION_PROFIT),
            PositionGetDouble(POSITION_VOLUME),
            (int)PositionGetInteger(POSITION_TYPE),
            PositionGetString(POSITION_COMMENT)
         );
         added++;
      }
   }
   pos_json += "]";
   
   // 2. PENDING ORDERS (AUDIT FIX)
   string ord_json = "[";
   int o_total = OrdersTotal();
   int o_added = 0;
   
   for(int i=0; i<o_total; i++) {
      ulong ticket = OrderGetTicket(i);
      if(OrderSelect(ticket)) {
         if(o_added > 0) ord_json += ",";

         string o_sym = OrderGetString(ORDER_SYMBOL);
         int o_dig = (int)SymbolInfoInteger(o_sym, SYMBOL_DIGITS);

         // Only send relevant info for tracking/cancelling
         ord_json += StringFormat(
            "{\"t\":%I64d,\"s\":\"%s\",\"p\":%s,\"sl\":%s,\"type\":%d,\"vol\":%.8f}",
            (long)ticket,
            o_sym,
            DoubleToString(OrderGetDouble(ORDER_PRICE_OPEN), o_dig),
            DoubleToString(OrderGetDouble(ORDER_SL), o_dig),
            (int)OrderGetInteger(ORDER_TYPE),
            OrderGetDouble(ORDER_VOLUME_INITIAL)
         );
         o_added++;
      }
   }
   ord_json += "]";

   // Send Combined State
   // pos: Positions (Market), orders: Pending (Limits)
   string json = StringFormat("{\"type\":\"HEARTBEAT\",\"mgmt_protocol\":2,\"bal\":%.2f,\"eq\":%.2f,\"pos\":%s,\"orders\":%s}",
                              AccountInfoDouble(ACCOUNT_BALANCE), 
                              AccountInfoDouble(ACCOUNT_EQUITY), 
                              pos_json,
                              ord_json);
   socket_push.Send(json);
}

//+------------------------------------------------------------------+
//| COMMAND HANDLER                                                  |
//+------------------------------------------------------------------+
void HandleCommand(string json) {
   // GET_HISTORY: Used by Backtest warmup
   if(StringFind(json, "GET_HISTORY") >= 0) {
      string sym = GetJSONString(json, "symbol");
      AddToWatchlist(sym);
      
      MqlRates rates[]; ArraySetAsSeries(rates, true);
      // "count" usually "500" from Python
      int bars_count = (int)GetJSONLong(json, "count");
      
      // Determine TF
      string tf_str = GetJSONString(json, "tf");
      ENUM_TIMEFRAMES tf = PERIOD_M5;
      if(tf_str == "H1") tf = PERIOD_H1;
      else if(tf_str == "H4") tf = PERIOD_H4;
      else if(tf_str == "D1") tf = PERIOD_D1;
      
      int copied = CopyRates(sym, tf, 0, bars_count, rates);
      
      if(copied > 0) {
         // v14.4: full precision (%G truncates BTC/index prices to 6 sig figs)
         int h_dig = (int)SymbolInfoInteger(sym, SYMBOL_DIGITS);
         // Construct minimal JSON manually to save memory
         string data = "[";
         for(int i=0; i<copied; i++) {
            data += StringFormat("{\"t\":%I64d,\"o\":%s,\"h\":%s,\"l\":%s,\"c\":%s}",
                                 rates[i].time,
                                 DoubleToString(rates[i].open, h_dig),
                                 DoubleToString(rates[i].high, h_dig),
                                 DoubleToString(rates[i].low, h_dig),
                                 DoubleToString(rates[i].close, h_dig));
            if(i < copied - 1) data += ",";
         }
         data += "]";
         
         string res = StringFormat("{\"type\":\"HISTORY\",\"symbol\":\"%s\",\"tf\":\"%s\",\"tv\":%G,\"ts\":%G,\"vm\":%G,\"vs\":%G,\"data\":%s}",
                                    sym, tf_str, 
                                    SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_VALUE), 
                                    SymbolInfoDouble(sym, SYMBOL_TRADE_TICK_SIZE),
                                    SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN), 
                                    SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP), data);
         socket_push.Send(res);
         Print("TITAN | Sent ", tf_str, " History for ", sym);
      }
   }
   
   // MODIFY SL/TP (v14.4.1: fire-and-forget path; Python verifies the result
   // via the HEARTBEAT position SL/TP instead of a synchronous ack, so a slow
   // or lost reply can never wedge the REQ/REP handshake socket)
   if(StringFind(json, "\"action\":\"MODIFY\"") >= 0) {
      MqlTradeRequest req; ZeroMemory(req); MqlTradeResult res; ZeroMemory(res);
      req.action   = TRADE_ACTION_SLTP;
      req.position = (ulong)GetJSONLong(json, "ticket");
      req.symbol   = GetJSONString(json, "symbol");
      req.sl       = GetJSONDouble(json, "sl");
      req.tp       = GetJSONDouble(json, "tp");
      if(!PositionSelectByTicket(req.position)) return;
      double live_sl = PositionGetDouble(POSITION_SL);
      if(live_sl > 0) {
         if(PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
            req.sl = MathMax(req.sl, live_sl);
         else if(req.sl <= 0 || req.sl > live_sl) req.sl = live_sl;
      }
      if(!OrderSend(req, res))
         Print("TITAN | Modify Failed: ", GetLastError());
      else if(res.retcode != TRADE_RETCODE_DONE)
         Print("TITAN | Modify Error: ", res.retcode, " ", res.comment);
      else
         Print("TITAN | Modified #", (long)req.position, " sl=", DoubleToString(req.sl, 5),
               " tp=", DoubleToString(req.tp, 5));
      return;
   }

   // CANCEL PENDING
   if(StringFind(json, "CANCEL") >= 0) {
      ulong t_id = (ulong)GetJSONLong(json, "ticket");
      MqlTradeRequest req; ZeroMemory(req); MqlTradeResult res; ZeroMemory(res);
      req.action = TRADE_ACTION_REMOVE;
      req.order  = t_id;
      if(!OrderSend(req, res)) Print("TITAN | Cancel Failed: ", res.retcode);
   }
   
   // CLOSE MARKET (full, or partial when a smaller "volume" is supplied)
   if(StringFind(json, "CLOSE_POS") >= 0 || StringFind(json, "CLOSE_TO_VOLUME") >= 0) {
      long t_id = GetJSONLong(json, "ticket");
      if(PositionSelectByTicket((ulong)t_id)) {
         MqlTradeRequest req; ZeroMemory(req); MqlTradeResult res; ZeroMemory(res);
         string sym = PositionGetString(POSITION_SYMBOL);
         req.action = TRADE_ACTION_DEAL;
         req.position = (ulong)t_id;
         req.symbol = sym;
         req.volume = PositionGetDouble(POSITION_VOLUME);
         // v14.4: Partial close support. Python's Dust Guard guarantees the
         // remainder stays >= the broker minimum lot.
         double vol_req = GetJSONDouble(json, "volume");
         bool targeted = StringFind(json, "CLOSE_TO_VOLUME") >= 0;
         string close_key = StringFormat("TitanClose.%I64d.%I64d", AccountInfoInteger(ACCOUNT_LOGIN), t_id);
         double before_volume = req.volume;
         if(targeted) {
            if(TargetCloseInFlight(close_key, before_volume)) return;
            double target = GetJSONDouble(json, "target_volume");
            if(StringFind(json, "\"target_volume\"") < 0 || !MathIsValidNumber(target)) return;
            if(target < 0 || target >= req.volume - 1e-9) return;
            double step = SymbolInfoDouble(sym, SYMBOL_VOLUME_STEP);
            double minimum = SymbolInfoDouble(sym, SYMBOL_VOLUME_MIN);
            if(step <= 0 || minimum <= 0) return;
            // Compute against live broker volume, not the Python snapshot.
            // Replaying this request after it filled is a no-op.
            req.volume = NormalizeDouble(MathFloor((req.volume-target+1e-9)/step)*step, 8);
            if(req.volume < minimum || (target > 1e-9 && target < minimum)) return;
         } else if(vol_req > 0 && vol_req < req.volume) req.volume = vol_req;
         req.type = (PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
         req.price = (req.type==ORDER_TYPE_BUY) ? SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);
         req.type_filling = GetFillingMode(sym);
         if(targeted) {
            // Durable before send: after an uncertain result or EA restart,
            // never submit a second close while the first may still execute.
            req.comment = "TitanReduce";
            if(GlobalVariableSet(close_key+".before", before_volume) == 0 ||
               GlobalVariableSet(close_key+".request", 0) == 0 ||
               GlobalVariableSet(close_key, -1.0) == 0) {
               Print("TITAN | Cannot persist close intent; refusing unsafe send");
               return;
            }
            GlobalVariablesFlush();
         }
         bool sent = OrderSend(req, res);
         if(targeted) {
            GlobalVariableSet(close_key+".request", (double)res.request_id);
            if(res.order > 0) GlobalVariableSet(close_key, (double)res.order);
            else if(TargetCloseRejected(res.retcode))
               ClearTargetClose(close_key); // definitive rejection: retry is safe
            GlobalVariablesFlush();
         }
         if(!sent || (res.retcode != TRADE_RETCODE_DONE && res.retcode != TRADE_RETCODE_DONE_PARTIAL))
            Print("TITAN | Close result: ", res.retcode, " ", res.comment);
      }
   }
}

//+------------------------------------------------------------------+
//| UTILS                                                            |
//+------------------------------------------------------------------+
bool TargetCloseRejected(uint code) {
   return code != TRADE_RETCODE_DONE && code != TRADE_RETCODE_DONE_PARTIAL &&
          code != TRADE_RETCODE_PLACED && code != TRADE_RETCODE_TIMEOUT &&
          code != TRADE_RETCODE_CONNECTION && code != 0;
}

void ClearTargetClose(string key) {
   GlobalVariableDel(key);
   GlobalVariableDel(key+".before");
   GlobalVariableDel(key+".request");
}

bool TargetCloseInFlight(string key, double live_volume) {
   if(!GlobalVariableCheck(key)) return false;
   long order = (long)GlobalVariableGet(key);
   // Unknown execution outcome stays blocked until broker volume confirms it.
   // A timeout is not a broker rejection (OrderSend documentation).
   if(order <= 0 || OrderSelect((ulong)order)) return true;
   if(!HistoryOrderSelect((ulong)order)) return true;
   long state = HistoryOrderGetInteger((ulong)order, ORDER_STATE);
   if(state != ORDER_STATE_FILLED && state != ORDER_STATE_CANCELED &&
      state != ORDER_STATE_REJECTED && state != ORDER_STATE_EXPIRED) return true;
   double filled = HistoryOrderGetDouble((ulong)order, ORDER_VOLUME_INITIAL) -
                   HistoryOrderGetDouble((ulong)order, ORDER_VOLUME_CURRENT);
   double before = GlobalVariableGet(key+".before");
   if(live_volume > before-filled+1e-9) return true; // wait for position update
   ClearTargetClose(key);
   return false;
}

ENUM_ORDER_TYPE_FILLING GetFillingMode(string symbol) {
   // Automatically find supported filling mode to prevent error 10030
   int filling = (int)SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
   if((filling & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
}

void OnTradeTransaction(const MqlTradeTransaction& trans, const MqlTradeRequest& request, const MqlTradeResult& result) {
   if(trans.type == TRADE_TRANSACTION_REQUEST && request.comment == "TitanReduce") {
      string key = StringFormat("TitanClose.%I64d.%I64d", AccountInfoInteger(ACCOUNT_LOGIN), (long)request.position);
      // A delayed callback from an earlier stage cannot replace the newer
      // stage's in-flight order identity.
      if(GlobalVariableCheck(key) && GlobalVariableCheck(key+".request") &&
         (uint)GlobalVariableGet(key+".request") == result.request_id) {
         if(result.order > 0) GlobalVariableSet(key, (double)result.order);
         else if(TargetCloseRejected(result.retcode)) ClearTargetClose(key);
         GlobalVariablesFlush();
      }
   }
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD) {
      if(HistoryDealSelect(trans.deal)) {
         long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
         // Detect Exit Deals (Closures)
         if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY) {
            ulong position_ticket = trans.position;
            double remaining = 0.0;
            if(PositionSelectByTicket(position_ticket))
               remaining = PositionGetDouble(POSITION_VOLUME);
            string status = (remaining > 0.0) ? "PARTIAL" : "CLOSED";
            string json = StringFormat("{\"type\":\"EXECUTION\",\"status\":\"%s\",\"ticket\":%I64d,\"deal\":%I64d,\"volume\":%G,\"remaining_volume\":%G,\"pn\":%G,\"s\":\"%s\"}",
                                        status, (long)position_ticket, (long)trans.deal,
                                        HistoryDealGetDouble(trans.deal, DEAL_VOLUME), remaining,
                                        HistoryDealGetDouble(trans.deal, DEAL_PROFIT), trans.symbol);
            socket_push.Send(json);
         }
      }
   }
}

void AddToWatchlist(string sym) {
   for(int i=0; i<ArraySize(watchlist); i++) if(watchlist[i] == sym) return;
   ArrayResize(watchlist, ArraySize(watchlist)+1);
   watchlist[ArraySize(watchlist)-1] = sym;
   SymbolSelect(sym, true);
}

// --- BASIC JSON PARSERS (Lightweight) ---
string GetJSONString(string json, string key) {
   string tag = "\"" + key + "\":\"";
   int s = StringFind(json, tag);
   if(s < 0) return "";
   s += StringLen(tag);
   int e = StringFind(json, "\"", s);
   if(e < 0) return "";
   return StringSubstr(json, s, e - s);
}
double GetJSONDouble(string json, string key) {
   string tag = "\"" + key + "\":";
   int s = StringFind(json, tag);
   if(s < 0) return 0.0;
   s += StringLen(tag);
   int e = StringFind(json, ",", s); 
   if(e < 0) e = StringFind(json, "}", s);
   return StringToDouble(StringSubstr(json, s, e - s));
}
long GetJSONLong(string json, string key) {
   return (long)GetJSONDouble(json, key);
}
