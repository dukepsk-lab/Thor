import os
import json
import time
import joblib
import pandas as pd
import numpy as np
import torch
import MetaTrader5 as mt5
from datetime import datetime

from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l1_features.trend_memory import calculate_ker
from src.layers.l1_features.volatility import calculate_yang_zhang, calculate_atr
from src.layers.l3_primary_model.cnn_model import TemporalCNN
from src.layers.l6_risk_sizing.sizing import calculate_base_size, apply_confidence_scaling
from src.layers.l7_execution.guards import ExecutionGuards
from src.layers.l7_execution.order_manager import OrderManager

class LiveBot:
    def __init__(self, symbol="EURUSD"):
        self.symbol = symbol
        self.timeframe = mt5.TIMEFRAME_M15
        self.balance = 10000.0 # Fallback balance
        self.model_dir = f'models/{self.symbol}'
        
        # -----------------------------------------
        # ⚙️ USER CONFIGURATION: Risk Management ⚙️
        # -----------------------------------------
        # 0.01 = 1% risk per trade (Safe)
        # 0.03 = 3% risk per trade (Aggressive)
        # 0.05 = 5% risk per trade (Very High Risk)
        self.risk_per_trade = 0.01 
        
        # Load constraints from Optimizer
        self.confidence_threshold = 0.5
        self.sl_multiplier = 2.0
        self.tp_multiplier = 2.0
        
        param_file = f'best_params_{self.symbol}.json'
        if os.path.exists(param_file):
            with open(param_file, 'r') as f:
                params = json.load(f)
                self.confidence_threshold = params.get('confidence_threshold', 0.5)
                self.sl_multiplier = params.get('sl_multiplier', 2.0)
                self.tp_multiplier = params.get('tp_multiplier', 2.0)
                self.risk_per_trade = params.get('risk_per_trade', 0.01)
                
        # Initialize execution components
        self.guards = ExecutionGuards(max_spread_points=30)
        self.order_manager = OrderManager(magic_number=777, slippage_points=10)
        
        print(f"Initializing LiveBot for {self.symbol}...")
        self.load_models()

    def load_models(self):
        if not os.path.exists(f'{self.model_dir}/hmm_model.pkl'):
            raise FileNotFoundError(f"Models for {self.symbol} not found. Please run train_and_save.py first!")
            
        print("Loading models from disk...")
        self.hmm = joblib.load(f'{self.model_dir}/hmm_model.pkl')
        
        import lightgbm as lgb
        self.tree = lgb.Booster(model_file=f'{self.model_dir}/lgb_model.txt')
        
        self.cnn = TemporalCNN(num_features=4, sequence_length=10, num_classes=3)
        self.cnn.load_state_dict(torch.load(f'{self.model_dir}/cnn_model.pt', weights_only=True))
        self.cnn.eval()
        
        self.meta = joblib.load(f'{self.model_dir}/meta_model.pkl')
        print("Models loaded successfully.")

    def run_cycle(self):
        print(f"\n[{datetime.now()}] Waking up to process new candle...")
        
        if not mt5_client.connect():
            print("MT5 connection failed. Skipping cycle.")
            return

        mt5.symbol_select(self.symbol, True)
        
        # 1. Fetch recent data (enough to calculate 20-period rolling features)
        rates = mt5.copy_rates_from_pos(self.symbol, self.timeframe, 0, 50)
        if rates is None or len(rates) < 30:
            print("Failed to fetch enough bars for feature calculation.")
            return
            
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        
        # 2. Compute Features
        df['return'] = df['close'].pct_change().fillna(0)
        df['volatility'] = calculate_yang_zhang(df, period=20).bfill()
        df['atr'] = calculate_atr(df, period=14).bfill()
        df['hurst'] = 0.5
        df['ker'] = calculate_ker(df, period=10).bfill()
        
        # Get the absolute latest closed bar (index -1)
        latest = df.iloc[-1:]
        
        # 3. Regime Prediction
        # hmmlearn expects 2D array
        regime_features = latest[['return', 'volatility']].values
        regime_state = self.hmm.predict(regime_features)[0]
        # simplified router logic for live demo
        current_regime = "trend" if regime_state == 0 else "range"
        
        # 4. Primary Prediction
        tree_features = latest[['return', 'volatility', 'hurst', 'ker']]
        # Tree outputs probability array [short, flat, long]
        tree_probas = self.tree.predict(tree_features)[0]
        
        # Mock CNN inference (requires sequence prep in production)
        # cnn_probas = [0.33, 0.33, 0.33]
        
        # Ensemble routing (simplified: trust tree if trend, else flat)
        primary_signal = 0
        if current_regime == "trend":
            predicted_class = np.argmax(tree_probas)
            primary_signal = -1 if predicted_class == 0 else (1 if predicted_class == 2 else 0)
            
        if primary_signal == 0:
            print("Signal: FLAT. Going back to sleep.")
            return
            
        print(f"Primary Signal Generated: {'LONG' if primary_signal == 1 else 'SHORT'}")
            
        # 5. Meta-Learner Filter
        meta_features = pd.DataFrame({
            'primary_signal': [primary_signal],
            'regime_trend': [1 if current_regime == 'trend' else 0],
            'volatility': latest['volatility'].values
        })
        
        # Get probability of class 1 (win)
        p_correct = self.meta.predict_proba(meta_features)[0][1]
        print(f"Meta-Learner Confidence: {p_correct:.1%}")
        
        # 6. Risk Sizing
        current_atr = latest['atr'].values[0]
        
        # Use real balance from MT5 if available
        account_info = mt5.account_info()
        real_balance = account_info.balance if account_info is not None else self.balance
        
        base_size = calculate_base_size(real_balance, self.risk_per_trade, current_atr, self.sl_multiplier) 
        
        final_size = apply_confidence_scaling(base_size, p_correct, self.confidence_threshold)
        
        if final_size <= 0:
            print("Trade rejected by Risk Sizing (Low Confidence).")
            return
            
        print(f"Approved Trade Size: {final_size} lots.")
            
        # 7. Execution Guards
        if not self.guards.is_safe_to_trade(self.symbol):
            print("Trade aborted by Execution Guards (e.g. Spread too wide).")
            return
            
        # 8. Fire Order
        print(">>> SENDING LIVE ORDER TO BROKER <<<")
        sl_points = int((current_atr * self.sl_multiplier) / mt5.symbol_info(self.symbol).point)
        tp_points = int((current_atr * self.tp_multiplier) / mt5.symbol_info(self.symbol).point)
        
        result = self.order_manager.send_market_order(
            self.symbol, 
            direction=primary_signal, 
            lot_size=round(final_size, 2), 
            sl_points=sl_points, 
            tp_points=tp_points
        )
        
        if result:
            print("Order Executed Successfully!")

def start_daemon(symbol="EURUSD"):
    print("=========================================")
    print(f"   THOR LIVE TRADING DAEMON: {symbol}    ")
    print("=========================================")
    bot = LiveBot(symbol=symbol)
    
    # In a true VPS environment, we check H4 boundaries or sleep
    # For now, run a cycle.
    bot.run_cycle()
    print("Cycle complete. Shutting down daemon.")

if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Run Live Trading Bot")
    parser.add_argument('--symbol', type=str, default='EURUSD', help='Symbol to trade')
    args = parser.parse_args()
    
    start_daemon(args.symbol)
