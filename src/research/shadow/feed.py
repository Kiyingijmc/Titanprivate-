"""GET-only transport: even an accidental broker write is blocked locally."""
import httpx
from src.execution.broker.mt5_http import MT5HttpBroker
from src.execution.broker.types import Timeframe


class ReadOnlyTransport(httpx.AsyncBaseTransport):
    def __init__(self,inner=None):
        self.inner=inner if inner is not None else httpx.AsyncHTTPTransport()

    async def handle_async_request(self,request):
        if request.method!='GET':
            raise RuntimeError('shadow transport permits GET only')
        return await self.inner.handle_async_request(request)

    async def aclose(self):
        await self.inner.aclose()


class Feed:
    def __init__(self):
        self._broker=MT5HttpBroker(timeout=5,enable_read_retry=False,transport=ReadOnlyTransport())

    async def __aenter__(self):
        await self._broker.__aenter__()
        return self

    async def __aexit__(self,*args):
        await self._broker.__aexit__(*args)

    async def quote(self,symbol):
        return await self._broker.get_current_tick(symbol)

    async def candles(self,symbol):
        return await self._broker.get_candles(symbol,Timeframe.M5,1800)
