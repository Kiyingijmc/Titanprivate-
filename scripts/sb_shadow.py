#!/usr/bin/env python3
"""Isolated prospective SilverBullet recorder and localhost comparison dashboard."""
import argparse
import asyncio
import fcntl
import hashlib
import json
from pathlib import Path
import signal
import sys
import time
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from dotenv import load_dotenv
import uvicorn
from src.research.shadow.store import Store, POLICY, CANDIDATES, SCENARIOS
from src.research.shadow.signals import market_epoch, observe_bars
from src.research.shadow.feed import Feed
from src.ops.web.shadow_view import create_app

SYMBOLS=('EURUSD','GBPUSD','USDJPY','AUDUSD','USDCAD','GBPJPY','XAUUSD','US30','BTCUSD')
POLL_SECONDS=2.
BAR_SECONDS=30.


def manifest():
    files=['src/research/shadow/store.py','src/research/shadow/signals.py','src/research/shadow/feed.py',
           'src/research/sb_entries.py','src/research/sb_variants.py','src/research/sb_sessions.py',
           'src/research/sb_session_range.py','src/research/sb_execution.py','src/research/costs.py',
           'src/utils/instrument.py','scripts/sb_shadow.py','data/specs.json',
           'docs/research/2026-09-18-sb-prospective-protocol.md']
    specs=json.loads((ROOT/'data/specs.json').read_text())
    return dict(version=1,symbols=list(SYMBOLS),candidates=list(CANDIDATES),scenarios=SCENARIOS,
        policy=POLICY,poll_seconds=POLL_SECONDS,bar_seconds=BAR_SECONDS,clock='seasonal_eet',
        commission='frozen modeled $7 round turn per lot converted with frozen tick specs',
        specs={s:specs[s] for s in SYMBOLS},
        source_sha256={f:hashlib.sha256((ROOT/f).read_bytes()).hexdigest() for f in files})


async def capture_quotes(feed,store,symbols=SYMBOLS):
    async def one(symbol):
        try:
            tick=await feed.quote(symbol)
            now=time.time()
            market=market_epoch(tick.time)
            store.quote(symbol,now,market,float(tick.bid),float(tick.ask),tick.time.isoformat())
        except Exception as exc:
            # Avoid serializing broker exception text: it may contain connection details.
            store.quote(symbol,time.time(),error='QUOTE_ERROR:'+type(exc).__name__)
    await asyncio.gather(*(one(symbol) for symbol in symbols))


async def capture_bars(feed,store,specs,symbols=SYMBOLS):
    # Fetch concurrently; serialize SQLite writes and detector evaluation on this loop.
    async def one(symbol):
        try:
            bars=await feed.candles(symbol)
            observe_bars(store,symbol,bars,specs[symbol],time.time())
        except Exception as exc:
            with store.db:
                store.event(time.time(),'BARS_ERROR',dict(symbol=symbol,error=type(exc).__name__))
    await asyncio.gather(*(one(symbol) for symbol in symbols))


async def run(args):
    load_dotenv(ROOT/'.env',override=False)
    args.directory.mkdir(parents=True,exist_ok=True)
    lock=(args.directory/'recorder.lock').open('a')
    try:
        fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
    except BlockingIOError:
        lock.close()
        raise RuntimeError('another recorder owns this cohort') from None
    store=None
    tasks=[]
    server=None
    try:
        frozen=manifest()
        store=Store(args.directory/'shadow.sqlite3',frozen,time.time())
        # The database manifest is authoritative; this readable copy has no secrets.
        (args.directory/'manifest.json').write_text(json.dumps(frozen,indent=2)+'\n')
        stopping=asyncio.Event()
        loop=asyncio.get_running_loop()
        for sig in (signal.SIGINT,signal.SIGTERM): loop.add_signal_handler(sig,stopping.set)
        async with Feed() as feed:
            await capture_quotes(feed,store)
            await capture_bars(feed,store,frozen['specs'])
            with store.db:
                store.set('status','RUNNING')
                store.set('heartbeat',time.time())
            if args.once:
                await capture_quotes(feed,store)
                print('Read-only collection cycle complete.',flush=True)
                return
            server=uvicorn.Server(uvicorn.Config(create_app(store.path),host='127.0.0.1',port=args.port,
                                                log_level='warning',access_log=False))
            # Our signal handlers stop collection and record censored active trades.
            server.install_signal_handlers=lambda:None
            async def quotes_loop():
                while not stopping.is_set():
                    started=loop.time()
                    await capture_quotes(feed,store)
                    await asyncio.sleep(max(.1,POLL_SECONDS-(loop.time()-started)))
            async def bars_loop():
                while not stopping.is_set():
                    await asyncio.sleep(BAR_SECONDS)
                    await capture_bars(feed,store,frozen['specs'])
            tasks=[asyncio.create_task(quotes_loop()),asyncio.create_task(bars_loop()),
                   asyncio.create_task(server.serve()),asyncio.create_task(stopping.wait())]
            print(f'Shadow recorder active. Dashboard: http://127.0.0.1:{args.port} ; directory: {args.directory}',flush=True)
            done,_=await asyncio.wait(tasks,return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                if task is not tasks[-1]: task.result()
    finally:
        if server: server.should_exit=True
        for task in tasks: task.cancel()
        if tasks: await asyncio.gather(*tasks,return_exceptions=True)
        if store:
            store.stop(time.time())
            store.close()
        fcntl.flock(lock,fcntl.LOCK_UN)
        lock.close()


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--directory',type=Path,required=True)
    ap.add_argument('--port',type=int,default=8772)
    ap.add_argument('--once',action='store_true',help='one read-only collection cycle; no persistent server')
    args=ap.parse_args()
    if not 1024<=args.port<=65535: ap.error('port must be 1024..65535')
    asyncio.run(run(args))


if __name__=='__main__': main()
