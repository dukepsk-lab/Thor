import os
import time
import MetaTrader5 as mt5
from datetime import datetime

from src.layers.l0_ingestion.mt5_client import mt5_client
from live_bot import LiveBot

def get_active_symbols():
    if not os.path.exists("models"):
        return []
    return [d for d in os.listdir("models") if os.path.isdir(os.path.join("models", d))]

def run_manager():
    print("=========================================")
    print("   THOR MASTER BOT MANAGER (VPS MODE)    ")
    print("=========================================")
    
    if not mt5_client.connect():
        print("CRITICAL: Failed to connect to MT5. Manager shutting down.")
        return
        
    print(f"[{datetime.now()}] Scanning for models...")
    symbols = get_active_symbols()
    if not symbols:
        print("No symbols found in models/. Please train models first.")
        return
        
    print(f"Found {len(symbols)} active symbols: {', '.join(symbols)}")
    
    bots = {}
    for sym in symbols:
        try:
            print(f"Initializing bot for {sym}...")
            bots[sym] = LiveBot(symbol=sym)
        except Exception as e:
            print(f"Failed to initialize {sym}: {e}")
            
    print("\n--- ENTERING INFINITE LOOP (CTRL+C to Stop) ---")
    
    cycle_interval = 300 # Sleep 5 minutes between checks
    
    while True:
        # Re-scan dynamically so adding a folder automatically picks it up on the next loop
        current_symbols = get_active_symbols()
        
        # Check for new symbols
        for sym in current_symbols:
            if sym not in bots:
                print(f"[{datetime.now()}] NEW SYMBOL DETECTED: {sym}. Initializing...")
                try:
                    bots[sym] = LiveBot(symbol=sym)
                except Exception as e:
                    print(f"Failed to initialize {sym}: {e}")
                    
        # Check for removed symbols
        for sym in list(bots.keys()):
            if sym not in current_symbols:
                print(f"[{datetime.now()}] SYMBOL REMOVED: {sym}. Stopping bot...")
                del bots[sym]
        
        # Run cycle for all active bots sequentially
        for sym, bot in bots.items():
            try:
                bot.run_cycle()
            except Exception as e:
                print(f"[{datetime.now()}] ERROR in {sym} run_cycle: {e}")
                
        print(f"[{datetime.now()}] Cycle complete. Sleeping for {cycle_interval/60} minutes...\n")
        time.sleep(cycle_interval)

if __name__ == "__main__":
    run_manager()
