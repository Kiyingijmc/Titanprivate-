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
double         last_bid_prices[]; 

//+------------------------------------------------------------------+
int OnInit() {
   // ZMQ Architecture:
   // Python (Brain) BINDS ports. MT5 (Gateway) CONNECTS to them.
   if(!socket_pull.Init() || !socket_push.Init() || !socket_rep.Init()) return INIT_FAILED;
   
   if(!socket_pull.Connect(ZMQ_PULL, StringFormat("tcp://%s:%d", InpIP, InpPullPort))) return INIT_FAILED;
   if(!socket_push.Connect(ZMQ_PUSH, StringFormat("tcp://%s:%d", InpIP, InpPushPort))) return INIT_FAILED;
   if(!socket_rep.Connect(ZMQ_REP,   StringFormat("tcp://%s:%d", InpIP, InpRepPort)))  return INIT_FAILED;
   
   Print("TITAN v14.3 PRO | Institutional Gateway Online.");
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
         bool success = ExecuteTrade(req_raw);
         // Respond JSON so Python 'reliable_send' stops blocking
         if(success) socket_rep.Send("{\"status\":\"OK\"}");
         else        socket_rep.Send("{\"status\":\"ERROR\"}");
      }
   }

   // --- 2. COMMAND LISTENER (Fire-and-forget) ---
   string cmd_raw = socket_pull.Recv();
   if(cmd_raw != "") HandleCommand(cmd_raw);

   // --- 3. TICK STREAMER ---
   int count = ArraySize(watchlist);
   if(ArraySize(last_bid_prices) != count) ArrayResize(last_bid_prices, count);

   for(int i=0; i<count; i++) {
      MqlTick t;
      if(SymbolInfoTick(watchlist[i], t)) {
         // Push only if price changes
         if(t.bid != last_bid_prices[i]) {
            // Using %I64d for millis
            string msg = StringFormat("{\"type\":\"TICK\",\"s\":\"%s\",\"b\":%G,\"a\":%G,\"t\":%I64d}",
                                       watchlist[i], t.bid, t.ask, t.time_msc);
            socket_push.Send(msg);
            last_bid_prices[i] = t.bid;
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
         
         // 'type' 0=BUY, 1=SELL in MT5
         pos_json += StringFormat(
            "{\"t\":%I64d,\"s\":\"%s\",\"p\":%G,\"sl\":%G,\"tp\":%G,\"pf\":%.2f,\"vol\":%.2f,\"type\":%d,\"comment\":\"%s\"}",
            (long)t_id,
            PositionGetString(POSITION_SYMBOL),
            PositionGetDouble(POSITION_PRICE_OPEN),
            PositionGetDouble(POSITION_SL),
            PositionGetDouble(POSITION_TP),
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
         
         // Only send relevant info for tracking/cancelling
         ord_json += StringFormat(
            "{\"t\":%I64d,\"s\":\"%s\",\"p\":%G,\"type\":%d,\"vol\":%.2f}",
            (long)ticket,
            OrderGetString(ORDER_SYMBOL),
            OrderGetDouble(ORDER_PRICE_OPEN),
            (int)OrderGetInteger(ORDER_TYPE),
            OrderGetDouble(ORDER_VOLUME_INITIAL)
         );
         o_added++;
      }
   }
   ord_json += "]";

   // Send Combined State
   // pos: Positions (Market), orders: Pending (Limits)
   string json = StringFormat("{\"type\":\"HEARTBEAT\",\"bal\":%.2f,\"eq\":%.2f,\"pos\":%s,\"orders\":%s}",
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
         // Construct minimal JSON manually to save memory
         string data = "[";
         for(int i=0; i<copied; i++) {
            data += StringFormat("{\"t\":%I64d,\"o\":%G,\"h\":%G,\"l\":%G,\"c\":%G}", 
                                 rates[i].time, rates[i].open, rates[i].high, rates[i].low, rates[i].close);
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
   
   // CANCEL PENDING
   if(StringFind(json, "CANCEL") >= 0) {
      ulong t_id = (ulong)GetJSONLong(json, "ticket");
      MqlTradeRequest req; ZeroMemory(req); MqlTradeResult res; ZeroMemory(res);
      req.action = TRADE_ACTION_REMOVE;
      req.order  = t_id;
      if(!OrderSend(req, res)) Print("TITAN | Cancel Failed: ", res.retcode);
   }
   
   // CLOSE MARKET (full, or partial when a smaller "volume" is supplied)
   if(StringFind(json, "CLOSE_POS") >= 0) {
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
         if(vol_req > 0 && vol_req < req.volume) req.volume = vol_req;
         req.type = (PositionGetInteger(POSITION_TYPE)==POSITION_TYPE_BUY) ? ORDER_TYPE_SELL : ORDER_TYPE_BUY;
         req.price = (req.type==ORDER_TYPE_BUY) ? SymbolInfoDouble(sym, SYMBOL_ASK) : SymbolInfoDouble(sym, SYMBOL_BID);
         req.type_filling = GetFillingMode(sym);
         if(!OrderSend(req, res)) Print("TITAN | Close Failed: ", res.retcode);
      }
   }
}

//+------------------------------------------------------------------+
//| UTILS                                                            |
//+------------------------------------------------------------------+
ENUM_ORDER_TYPE_FILLING GetFillingMode(string symbol) {
   // Automatically find supported filling mode to prevent error 10030
   int filling = (int)SymbolInfoInteger(symbol, SYMBOL_FILLING_MODE);
   if((filling & SYMBOL_FILLING_FOK) != 0) return ORDER_FILLING_FOK;
   if((filling & SYMBOL_FILLING_IOC) != 0) return ORDER_FILLING_IOC;
   return ORDER_FILLING_RETURN;
}

void OnTradeTransaction(const MqlTradeTransaction& trans, const MqlTradeRequest& request, const MqlTradeResult& result) {
   if(trans.type == TRADE_TRANSACTION_DEAL_ADD) {
      if(HistoryDealSelect(trans.deal)) {
         long entry = HistoryDealGetInteger(trans.deal, DEAL_ENTRY);
         // Detect Exit Deals (Closures)
         if(entry == DEAL_ENTRY_OUT || entry == DEAL_ENTRY_OUT_BY) {
            string json = StringFormat("{\"type\":\"EXECUTION\",\"status\":\"CLOSED\",\"ticket\":%I64d,\"pn\":%G,\"s\":\"%s\"}",
                                        (long)trans.position, HistoryDealGetDouble(trans.deal, DEAL_PROFIT), trans.symbol);
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