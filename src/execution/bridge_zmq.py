# ==============================================================================
# FILE: src/execution/bridge_zmq.py
# TYPE: PERFORMANCE UPDATE (High-Frequency Ingestion)
# AUDIT: 
#   1. "Queue Drain" Implementation: Reads ALL pending ZMQ messages per loop 
#      instead of just one. Prevents "Lag" / "Stuck Status" on active feeds.
#   2. Retained JSON Protocol format.
# STATUS: PRODUCTION READY
# ==============================================================================

import zmq
import zmq.asyncio
import json
import asyncio

class ZMQBridge:
    def __init__(self, push_port=32768, pull_port=32769, req_port=32770):
        self.context = zmq.asyncio.Context()
        
        # 1. PUSH: Commands (Py -> MT5)
        self.push_port = push_port
        self.socket_push = self.context.socket(zmq.PUSH)
        self.socket_push.setsockopt(zmq.SNDHWM, 1000)
        try: 
            self.socket_push.bind(f"tcp://*:{self.push_port}")
        except zmq.ZMQError as e:
            print(f"[ZMQ ERROR] Failed to bind PUSH: {e}")
        
        # 2. PULL: Data (MT5 -> Py)
        self.pull_port = pull_port
        self.socket_pull = self.context.socket(zmq.PULL)
        # Increase High Water Mark to prevent dropping packets during heavy bursts
        self.socket_pull.setsockopt(zmq.RCVHWM, 10000)
        self.socket_pull.setsockopt(zmq.RCVBUF, 10 * 1024 * 1024) 
        try: 
            self.socket_pull.bind(f"tcp://*:{self.pull_port}")
        except zmq.ZMQError as e:
             print(f"[ZMQ ERROR] Failed to bind PULL: {e}")

        # 3. REQ: Handshake (Reliable)
        self.req_port = req_port
        self.socket_req = None
        self._init_req_socket()

    def _init_req_socket(self):
        """Helper to init or reset the REQ socket."""
        if self.socket_req:
            self.socket_req.close()
            
        self.socket_req = self.context.socket(zmq.REQ)
        self.socket_req.setsockopt(zmq.LINGER, 0)
        try: 
            self.socket_req.bind(f"tcp://*:{self.req_port}")
        except zmq.ZMQError as e:
            print(f"[ZMQ ERROR] Failed to bind REQ: {e}")

    def _pack_json(self, payload):
        """Force compact JSON for MQL5 compatibility."""
        return json.dumps(payload, separators=(',', ':')).encode('utf-8')

    async def send_command(self, action, payload=None):
        if payload is None: payload = {}
        payload['action'] = action
        try:
            await self.socket_push.send(self._pack_json(payload))
            return True
        except Exception:
            return False

    async def send_order_reliable(self, payload, timeout=2500):
        try:
            await self.socket_req.send(self._pack_json(payload))
            if await self.socket_req.poll(timeout=timeout):
                reply = await self.socket_req.recv_json()
                return reply.get('status') == 'OK' or reply.get('ticket', 0) > 0
            else:
                print(f"[ZMQ WARN] REQ Timeout on {payload.get('symbol', '?')}. Resetting.")
                self._init_req_socket()
                return False
        except Exception as e:
            print(f"[ZMQ FAIL] Reliable Send Error: {e}")
            self._init_req_socket()
            return False

    async def ping(self):
        return await self.send_order_reliable({"action": "PING"}, timeout=1000)

    async def poll_data(self):
        """
        AUDIT FIX: Drain the buffer!
        Reads ALL available messages in the queue up to a limit (e.g. 500),
        ensuring we don't fall behind the live Tick stream.
        """
        batch = []
        limit = 500 # Prevent infinite loops if spamming, but allow burst catch-up
        
        try:
            # We use a loop to consume everything waiting in the kernel buffer
            for _ in range(limit):
                # NOBLOCK ensures we don't wait if buffer is empty
                # We check events first to see if read is ready
                try:
                    # Async recv
                    raw_bytes = await self.socket_pull.recv(flags=zmq.NOBLOCK)
                    raw = raw_bytes.decode('utf-8', errors='ignore')
                    
                    # Sticky Packet Splitter
                    dec = json.JSONDecoder()
                    idx = 0
                    while idx < len(raw):
                        if raw[idx].isspace(): 
                            idx += 1
                            continue
                        try:
                            o, end = dec.raw_decode(raw, idx)
                            batch.append(o)
                            idx = end
                        except json.JSONDecodeError:
                            break
                            
                except zmq.Again:
                    # Buffer Empty - we are caught up
                    break
                    
            return batch
            
        except Exception as e:
            # print(f"ZMQ Error: {e}")
            return batch