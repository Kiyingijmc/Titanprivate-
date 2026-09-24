"""Execute the gateway's actual close-retry guard with stubbed MT5 state.

This checks its state machine using C++, whose subset these MQL helpers share.
It does not replace compiling the complete EA with MetaEditor.
"""
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest


@unittest.skipUnless(shutil.which('g++'), 'C++ compiler unavailable')
class GatewayCloseGuardTests(unittest.TestCase):
    def test_pending_unknown_rejected_partial_and_filled_orders(self):
        source = (Path(__file__).resolve().parents[2] /
                  'mql5_bridge/Experts/Titan_Gateway.mq5').read_text()
        helpers = source[source.index('bool TargetCloseRejected('):
                         source.index('ENUM_ORDER_TYPE_FILLING GetFillingMode(')]
        harness = r'''
#include <cassert>
#include <string>
#include <map>
using string = std::string;
using uint = unsigned int;
std::map<string, double> globals;
bool active = false, history = true;
long state = 1;
double initial = .3, outstanding = 0;
enum { ORDER_STATE_FILLED=1, ORDER_STATE_CANCELED, ORDER_STATE_REJECTED,
       ORDER_STATE_EXPIRED, ORDER_STATE_PARTIAL, ORDER_STATE,
       ORDER_VOLUME_INITIAL, ORDER_VOLUME_CURRENT };
enum { TRADE_RETCODE_DONE=10, TRADE_RETCODE_DONE_PARTIAL, TRADE_RETCODE_PLACED,
       TRADE_RETCODE_TIMEOUT, TRADE_RETCODE_CONNECTION, TRADE_RETCODE_REJECT };
bool GlobalVariableCheck(string k) { return globals.count(k); }
double GlobalVariableGet(string k) { return globals.at(k); }
void GlobalVariableDel(string k) { globals.erase(k); }
bool OrderSelect(unsigned long) { return active; }
bool HistoryOrderSelect(unsigned long) { return history; }
long HistoryOrderGetInteger(unsigned long, int) { return state; }
double HistoryOrderGetDouble(unsigned long, int field) {
    return field == ORDER_VOLUME_INITIAL ? initial : outstanding;
}
'''
        assertions = r'''
int main() {
    assert(!TargetCloseInFlight("k", 1.0));
    globals["k"]=-1; globals["k.before"]=1;
    assert(TargetCloseInFlight("k", 1)); // unknown outcome cannot be retried
    globals["k"]=123; active=true;
    assert(TargetCloseInFlight("k", .7)); // active order even if volume fell
    active=false; history=false;
    assert(TargetCloseInFlight("k", 1)); // no history is not a rejection
    history=true; state=ORDER_STATE_FILLED;
    assert(TargetCloseInFlight("k", 1)); // fill notification ahead of position
    assert(!TargetCloseInFlight("k", .7));
    assert(!GlobalVariableCheck("k"));
    globals["k"]=124; globals["k.before"]=1;
    state=ORDER_STATE_CANCELED; outstanding=.2;
    assert(TargetCloseInFlight("k", 1));
    assert(!TargetCloseInFlight("k", .9)); // IOC partial: only remainder retries
    globals["k"]=125; globals["k.before"]=1;
    state=ORDER_STATE_REJECTED; outstanding=.3;
    assert(!TargetCloseInFlight("k", 1));
    assert(TargetCloseRejected(TRADE_RETCODE_REJECT));
    assert(!TargetCloseRejected(TRADE_RETCODE_TIMEOUT));
    assert(!TargetCloseRejected(TRADE_RETCODE_CONNECTION));
    assert(!TargetCloseRejected(TRADE_RETCODE_DONE_PARTIAL));
}
'''
        with tempfile.TemporaryDirectory() as directory:
            cpp = Path(directory) / 'guard.cpp'
            exe = Path(directory) / 'guard'
            cpp.write_text(harness + helpers + assertions)
            compiled = subprocess.run(['g++', '-std=c++17', str(cpp), '-o', str(exe)],
                                      capture_output=True, text=True, timeout=30)
            self.assertEqual(compiled.returncode, 0, compiled.stderr)
            checked = subprocess.run([str(exe)], capture_output=True, text=True, timeout=10)
            self.assertEqual(checked.returncode, 0, checked.stderr)
