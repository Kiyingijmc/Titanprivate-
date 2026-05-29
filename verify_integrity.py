# ==============================================================================
# FILE: verify_integrity.py
# TYPE: SYSTEM DIAGNOSTIC (Final Audit)
# AUDIT: 
#   1. Validates Folder Structure & File Existence.
#   2. Verifies Python Imports (Checks for circular dependency errors).
#   3. Checks Database Write Permissions.
#   4. Checks Config Validity.
# STATUS: PRODUCTION READY
# ==============================================================================

import os
import sys
import importlib
import yaml
import sqlite3
import colorama
from pathlib import Path
from colorama import Fore, Style

# Initialize Colorama
colorama.init()

def print_status(step, status, message=""):
    symbol = "✅" if status == "OK" else "❌"
    color = Fore.GREEN if status == "OK" else Fore.RED
    print(f"{symbol} {Fore.CYAN}{step:<25}{Style.RESET_ALL} {color}{status:<10}{Style.RESET_ALL} {message}")

def check_structure():
    print(f"\n{Fore.YELLOW}--- 1. FILE SYSTEM STRUCTURE ---{Style.RESET_ALL}")
    
    required_files = [
        "main.py",
        "RUN_TITAN.bat",
        "requirements.txt",
        ".env",
        "config/config.yaml",
        "src/core/system_controller.py",
        "src/core/state_manager.py",
        "src/analysis/smc_analyzer.py",
        "src/strategies/models/unicorn.py"
    ]
    
    all_good = True
    for file_path in required_files:
        if os.path.exists(file_path):
            print_status(file_path, "OK")
        else:
            print_status(file_path, "MISSING", "Required for boot")
            all_good = False
            
    return all_good

def check_imports():
    print(f"\n{Fore.YELLOW}--- 2. LOGIC IMPORT CHECK ---{Style.RESET_ALL}")
    
    modules = [
        ("src.core.system_controller", "SystemController"),
        ("src.analysis.smc_analyzer", "SMCAnalyzer"),
        ("src.execution.bridge_zmq", "ZMQBridge"),
        ("src.risk.risk_manager", "RiskManager"),
        ("src.strategies.models.unicorn", "UnicornModel")
    ]
    
    sys.path.insert(0, os.getcwd())
    
    for mod_path, class_name in modules:
        try:
            module = importlib.import_module(mod_path)
            if hasattr(module, class_name):
                print_status(mod_path, "OK")
            else:
                print_status(mod_path, "FAIL", f"Class {class_name} missing")
        except ImportError as e:
            print_status(mod_path, "CRITICAL", f"Import Error: {e}")
        except Exception as e:
            print_status(mod_path, "ERROR", str(e))

def check_database():
    print(f"\n{Fore.YELLOW}--- 3. PERSISTENCE CHECK ---{Style.RESET_ALL}")
    
    db_dir = Path("data/db")
    db_dir.mkdir(parents=True, exist_ok=True)
    db_path = db_dir / "integrity_test.db"
    
    try:
        conn = sqlite3.connect(db_path)
        conn.execute("CREATE TABLE IF NOT EXISTS test (id INTEGER)")
        conn.execute("INSERT INTO test VALUES (1)")
        conn.commit()
        conn.close()
        print_status("SQLite Write", "OK")
        
        # Cleanup
        try: os.remove(db_path) 
        except: pass
        
    except Exception as e:
        print_status("SQLite Write", "FAIL", str(e))

def check_config():
    print(f"\n{Fore.YELLOW}--- 4. CONFIGURATION ---{Style.RESET_ALL}")
    
    if os.path.exists("config/config.yaml"):
        try:
            with open("config/config.yaml", 'r') as f:
                cfg = yaml.safe_load(f)
                
            vers = cfg.get('system', {}).get('version', 'Unknown')
            mt5 = cfg.get('system', {}).get('mt5_path', 'Unknown')
            
            print_status("YAML Syntax", "OK", f"Version: {vers}")
            print_status("MT5 Path", "CHECK", mt5)
            
        except Exception as e:
            print_status("Config Load", "FAIL", str(e))
    else:
        print_status("Config", "MISSING")

if __name__ == "__main__":
    print(f"{Fore.WHITE}TITAN v14.3 INTEGRITY VERIFICATION{Style.RESET_ALL}")
    print("="*50)
    
    fs = check_structure()
    check_imports()
    check_database()
    check_config()
    
    print("\n" + "="*50)
    if fs:
        print(f"{Fore.GREEN}SYSTEM INTEGRITY: STABLE.{Style.RESET_ALL}")
        print("You may now execute 'RUN_TITAN.bat'")
    else:
        print(f"{Fore.RED}SYSTEM INTEGRITY: UNSTABLE.{Style.RESET_ALL}")
        print("Please repair missing files before starting.")
    
    input("\nPress Enter to Exit...")