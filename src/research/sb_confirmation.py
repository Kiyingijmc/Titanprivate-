"""Causal M5 confirmation research. No live execution dependencies."""
import math
import numpy as np
from src.research.sb_execution import replay_order


def confirm_order(signal, bars, *, path, spread, commission):
    """Observe closed M5 bars, then enter on the next executable open.

    Caller supplies validated uninterrupted M5 bars and complete lifecycle
    coverage. One attempt per parent; rejected confirmations consume its cap.
    """
    side = 1 if signal['dir'] == 'BUY' else -1
    if signal['dir'] not in ('BUY', 'SELL'):
        raise ValueError('invalid direction')
    midpoint, parent_risk = float(signal['entry']), float(signal['risk'])
    if not all(math.isfinite(x) for x in (midpoint, parent_risk, spread, commission)) or min(midpoint, parent_risk)<=0 or min(spread, commission)<0:
        raise ValueError('invalid geometry or costs')
    stop = midpoint-side*parent_risk
    created = np.datetime64(signal['time'], 'ns')+np.timedelta64(15, 'm')
    if np.isnat(created):
        raise ValueError('invalid timestamp')
    expiry = created+np.timedelta64(45, 'm')
    t = bars['time']
    start = int(np.searchsorted(t, created))
    if start < 1 or start >= len(t) or t[start] != created:
        raise ValueError('missing parent-close or prior bar')
    touched = False

    def rejected(outcome, release):
        return dict(time=str(signal['time']), dir=signal['dir'], entry=midpoint,
                    risk=parent_risk, parent_risk=parent_risk, created=str(created),
                    release=str(release), fill_idx=None, exit_idx=None,
                    outcome=outcome, gross_r=None, net_r=None, rejected_be=0,
                    confirmation_close=None, risk_ratio=None)

    for k in range(start, len(t)):
        if t[k] >= expiry:
            return rejected('NO_CONFIRMATION', expiry)
        if t[k]-t[k-1] != np.timedelta64(5, 'm'):
            raise ValueError('gap while awaiting confirmation')
        o,h,l,c = (float(bars[key][k]) for key in ('open','high','low','close'))
        if (l <= stop if side==1 else h+spread >= stop):
            return rejected('INVALIDATED', t[k]+np.timedelta64(5,'m'))
        touched |= l+spread <= midpoint if side==1 else h >= midpoint
        broken = c > bars['high'][k-1] if side==1 else c < bars['low'][k-1]
        if not (touched and side*(c-o)>0 and side*(c-midpoint)>0 and broken):
            continue
        available = t[k]+np.timedelta64(5,'m')
        if available >= expiry:
            return rejected('NO_CONFIRMATION', expiry)
        if k+1 >= len(t) or t[k+1] != available:
            raise ValueError('missing next-open entry')
        entry = float(bars['open'][k+1])+(spread if side==1 else 0.)
        risk = side*(entry-stop)
        # Reject gaps through the stop at the executable liquidation quote.
        liquidation = float(bars['open'][k+1])+(spread if side==-1 else 0.)
        if side*(liquidation-stop)<=0 or entry<=0 or risk<=0 or entry+side*2*risk<=0:
            return rejected('ENTRY_INVALID', available)
        if (spread+commission)/risk > .25:
            return rejected('ENTRY_COST', available)
        market = dict(signal, time=str(t[k]), entry=entry, risk=risk)
        row = replay_order(market, bars, arm='fixed', path=path, spread=spread,
                           commission=commission, signal_minutes=5, ttl_minutes=5,
                           max_hold_minutes=180)
        if row['fill_idx'] != k+1:
            raise AssertionError('next-open market fill was not immediate')
        row.update(time=str(signal['time']), created=str(created), parent_risk=parent_risk,
                   confirmation_close=str(available), risk_ratio=risk/parent_risk)
        return row
    raise ValueError('incomplete confirmation horizon')
