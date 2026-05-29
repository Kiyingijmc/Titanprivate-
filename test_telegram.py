# ==============================================================================
# FILE: test_telegram.py
# TYPE: DIAGNOSTIC SCRIPT
# AUDIT: 
#   1. Improved Error Semantics (Distinguishes Bad Token vs Bad Chat ID).
#   2. Robust .env loading using relative paths.
#   3. Network connectivity validation independent of main logic.
# STATUS: PRODUCTION READY
# ==============================================================================

import os
import sys
import asyncio
import requests
from pathlib import Path
from dotenv import load_dotenv

# 1. Path Setup: Ensure we can find the project root
ROOT_DIR = Path(__file__).parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))

# Mock Logger for consistency with project structure
class MockLogger:
    def log_event(self, type, module, msg):
        print(f"[{type}] {module}: {msg}")

async def test():
    print("--- TITAN TELEMETRY DIAGNOSTIC ---")
    
    # 2. Robust Environment Loading
    env_path = ROOT_DIR / ".env"
    if env_path.exists():
        load_dotenv(dotenv_path=env_path)
        print(f"1. Loading .env file...       [OK]")
    else:
        print(f"1. Loading .env file...       [MISSING]")
        print("   ❌ Error: .env file not found in project root.")
        return

    token = os.getenv("TELEGRAM_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    
    # 3. Credential Validation
    token_status = "[FOUND]" if token and token != "x" else "[MISSING/DEFAULT]"
    print(f"2. Checking Token...          {token_status}")
    if token and len(token) > 10: 
        print(f"   Value: {token[:5]}*******")
    
    chat_status = "[FOUND]" if chat_id else "[MISSING]"
    print(f"3. Checking Chat ID...        {chat_status}")
    if chat_id: 
        print(f"   Value: {chat_id}")
    
    if not token or not chat_id or token == "x":
        print("\n❌ STOP: Please edit your .env file with real Telegram credentials!")
        return

    # 4. Active Connectivity Test
    print("4. Attempting Network Request...")
    
    # We use raw requests to isolate network issues from Bot Logic class issues
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id, 
        "text": "✅ **Titan System:** Connectivity Check Successful.", 
        "parse_mode": "Markdown"
    }
    
    try:
        # Run in executor to simulate async behavior of the bot
        response = await asyncio.to_thread(requests.post, url, json=payload, timeout=10)
        
        print(f"5. Server HTTP Response:      [{response.status_code}]")
        
        if response.status_code == 200:
            print("\n✅ SUCCESS: Message sent. Check your Telegram App now.")
            return
            
        # 5. Semantic Error Diagnosis
        data = response.json()
        desc = data.get("description", "Unknown Error")
        
        print(f"\n❌ FAIL: Telegram API refused connection.")
        print(f"   Reason: {desc}")
        
        if response.status_code == 401:
            print("   👉 Diagnosis: YOUR TOKEN IS INCORRECT.")
        elif response.status_code == 400:
            print("   👉 Diagnosis: YOUR CHAT ID IS INCORRECT (or Bot hasn't been started).")
        
    except requests.exceptions.ConnectionError:
        print("\n❌ FAIL: Could not connect to api.telegram.org.")
        print("   👉 Diagnosis: Check your Internet Connection or DNS.")
    except Exception as e:
        print(f"\n❌ UNEXPECTED ERROR: {e}")

if __name__ == "__main__":
    if sys.platform == 'win32':
        asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())
    asyncio.run(test())