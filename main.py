# ==============================================================================
# FILE: main.py
# TYPE: ENTRY POINT (Bootstrap & Safety)
# AUDIT: 
#   1. Added Python Version Guard (Requires 3.10+).
#   2. Implemented Fatal Error Logging (boot_crash.log).
#   3. Secure sys.path injection for robust import resolution.
# STATUS: PRODUCTION READY
# ==============================================================================

import asyncio
import sys
import os
import traceback
from datetime import datetime

# 1. Environment Guard: Ensure Python 3.10+
if sys.version_info < (3, 10):
    print("❌ FATAL: Titan Bot requires Python 3.10 or higher.")
    print(f"   Current Version: {sys.version.split()[0]}")
    input("Press Enter to Exit...")
    sys.exit(1)

# 2. Path Bootstrap: Ensure Project Root is in Path
# This prevents "ModuleNotFoundError" if ran from subfolders or via odd shell contexts
ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

# 3. Import Core Controller (Lazy import after path fix)
try:
    from src.core.system_controller import SystemController
except ImportError as e:
    print(f"❌ FATAL IMPORT ERROR: {e}")
    print("   Ensure you have installed requirements.txt")
    print("   Run: pip install -r requirements.txt")
    input("Press Enter to Exit...")
    sys.exit(1)

async def main():
    """
    Main Async Entry Point.
    """
    print(f"[{datetime.now().strftime('%H:%M:%S')}] BOOTSTRAPPING TITAN KERNEL...")
    
    # Initialize the Master Controller
    # (This triggers Config Load, DB Connect, and ZMQ Bind)
    bot = SystemController()
    
    try:
        # Transfer control to the Event Loop
        await bot.run()
    except asyncio.CancelledError:
        print("\n[STOP] System stop requested.")
    except Exception as e:
        # Catch unexpected runtime crashes that bubble up from Controller
        print(f"\n[CRASH] Runtime Exception: {e}")
        traceback.print_exc()
        raise e

if __name__ == '__main__':
    # 4. OS-Specific Loop Policy (Required for ZMQ on Windows)
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        # Clean exit on Ctrl+C
        print("\n[STOP] Titan system closed by user (KeyboardInterrupt).")
    except Exception as fatal:
        # 5. Last Resort Logging (Filesystem)
        # Captures crashes that occur before internal Logging is ready
        err_msg = f"{datetime.now()} - FATAL BOOT CRASH:\n{traceback.format_exc()}\n"
        print("❌ FATAL ERROR. See boot_crash.log for details.")
        
        try:
            with open("boot_crash.log", "a") as f:
                f.write(err_msg)
        except:
            pass # If we can't write to disk, we really can't do anything else.
        
        input("Press Enter to Exit...")