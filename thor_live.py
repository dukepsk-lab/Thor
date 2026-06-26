# ============================================================
# THOR AI - Live Trading Module
# ============================================================
# Strategy : Thor ML Ensemble (LightGBM + HMM + CNN + Meta)
# Symbols  : USDJPY, GBPUSD
# Lot Rule : Dynamic 0.01 lot per $100 equity
# Timeframe: H4
# Comment  : All orders tagged "THOR" in MT5 trade history
# ============================================================

import os
import json
import time
import sched
import logging
import joblib
import pandas as pd
import numpy as np
import torch
import MetaTrader5 as mt5
from datetime import datetime, timedelta

from src.layers.l0_ingestion.mt5_client import mt5_client
from src.layers.l1_features.trend_memory import calculate_ker
from src.layers.l1_features.volatility import calculate_yang_zhang, calculate_atr
from src.layers.l3_primary_model.cnn_model import TemporalCNN
from src.layers.l7_execution.guards import ExecutionGuards
from src.layers.l7_execution.order_manager import OrderManager

# ============================================================
# Logging Configuration — เทรดจาก THOR
# ============================================================
LOG_DIR = 'logs'
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [THOR] %(levelname)s — %(message)s',
    handlers=[
        logging.FileHandler(f'{LOG_DIR}/thor_live_{datetime.now().strftime("%Y%m%d")}.log'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger('THOR')

# ============================================================
# THOR Configuration — เทรดจาก THOR
# ============================================================
THOR_CONFIG = {
    # สินทรัพย์ที่เทรด (เฉพาะคู่ที่ผ่าน Backtest 1 ปี)
    'symbols': ['USDJPY', 'GBPUSD'],
    
    # Dynamic Lot Sizing: 0.01 lot ต่อ equity $100
    'lot_per_100': 0.01,
    
    # Timeframe
    'timeframe': mt5.TIMEFRAME_H4,
    
    # H4 cycle interval (4 hours = 14400 seconds)
    'cycle_interval_sec': 14400,
    
    # Magic Number สำหรับระบุออเดอร์ THOR
    'magic_number': 7777,
    
    # Comment ที่จะติดไปกับทุกออเดอร์
    'order_comment': 'THOR',
    
    # Max spread (points) ก่อนเข้าเทรด
    'max_spread_points': 30,
    
    # Slippage tolerance (points)
    'slippage_points': 10,
    
    # Feature columns per symbol
    'features': {
        'USDJPY': ['return', 'volatility'],
        'GBPUSD': ['return', 'volatility'],
    },
    
    # CNN input dimensions per symbol
    'cnn_num_features': {
        'USDJPY': 2,
        'GBPUSD': 2,
    }
}


# ============================================================
# ThorSymbolTrader — เทรดจาก THOR (per-symbol logic)
# ============================================================
class ThorSymbolTrader:
    """
    เทรดจาก THOR — Handles ML inference and trade execution
    for a single symbol using the Thor ensemble pipeline.
    """
    
    def __init__(self, symbol: str, config: dict):
        self.symbol = symbol
        self.config = config
        self.model_dir = f'models/{symbol}'
        
        # Load optimized parameters from Optuna
        self.confidence_threshold = 0.5
        self.sl_multiplier = 2.0
        self.tp_multiplier = 2.0
        self._load_params()
        
        # Feature columns for this symbol
        self.feature_cols = config['features'].get(symbol, ['return', 'volatility'])
        self.cnn_features = config['cnn_num_features'].get(symbol, 2)
        
        # Execution components
        self.guards = ExecutionGuards(max_spread_points=config['max_spread_points'])
        self.order_manager = OrderManager(
            magic_number=config['magic_number'],
            slippage_points=config['slippage_points']
        )
        # Override order comment to THOR
        self.order_manager.comment = config['order_comment']
        
        # Load ML models
        self._load_models()
        
    def _load_params(self):
        """Load optimized params from best_params_<SYMBOL>.json — เทรดจาก THOR"""
        param_file = f'best_params_{self.symbol}.json'
        if os.path.exists(param_file):
            with open(param_file, 'r') as f:
                params = json.load(f)
                self.confidence_threshold = params.get('confidence_threshold', 0.5)
                self.sl_multiplier = params.get('sl_multiplier', 2.0)
                self.tp_multiplier = params.get('tp_multiplier', 2.0)
            logger.info(f"[{self.symbol}] Loaded params: conf={self.confidence_threshold:.4f}, "
                        f"SL={self.sl_multiplier:.2f}x, TP={self.tp_multiplier:.2f}x")
        else:
            logger.warning(f"[{self.symbol}] No params file found, using defaults.")
    
    def _load_models(self):
        """Load all ML models from disk — เทรดจาก THOR"""
        if not os.path.exists(f'{self.model_dir}/hmm_model.pkl'):
            raise FileNotFoundError(
                f"[THOR] Models for {self.symbol} not found in {self.model_dir}. "
                f"Run train_and_save.py --symbol {self.symbol} first!"
            )
        
        logger.info(f"[{self.symbol}] Loading THOR models...")
        
        self.hmm = joblib.load(f'{self.model_dir}/hmm_model.pkl')
        
        import lightgbm as lgb
        self.tree = lgb.Booster(model_file=f'{self.model_dir}/lgb_model.txt')
        
        self.cnn = TemporalCNN(
            num_features=self.cnn_features,
            sequence_length=10,
            num_classes=3
        )
        self.cnn.load_state_dict(
            torch.load(f'{self.model_dir}/cnn_model.pt', weights_only=True)
        )
        self.cnn.eval()
        
        self.meta = joblib.load(f'{self.model_dir}/meta_model.pkl')
        logger.info(f"[{self.symbol}] THOR models loaded successfully.")
    
    def _calculate_dynamic_lot(self, equity: float) -> float:
        """
        Dynamic Lot Sizing — เทรดจาก THOR
        Rule: 0.01 lot per $100 equity
        Example: equity $300 → 0.03 lot
        """
        lot = (equity / 100.0) * self.config['lot_per_100']
        # Normalize to MT5 volume step
        lot = self.order_manager.normalize_volume(self.symbol, lot)
        return lot
    
    def _compute_features(self, df: pd.DataFrame) -> pd.DataFrame:
        """Compute all features needed for THOR inference."""
        df = df.copy()
        df['return'] = df['close'].pct_change().fillna(0)
        df['volatility'] = calculate_yang_zhang(df, period=20).bfill()
        df['atr'] = calculate_atr(df, period=14).bfill()
        df['hurst'] = 0.5
        df['ker'] = calculate_ker(df, period=10).bfill()
        return df
    
    def _predict(self, df: pd.DataFrame) -> tuple:
        """
        Run the full THOR ensemble pipeline — เทรดจาก THOR
        Returns: (final_signal, confidence, regime)
        """
        latest = df.iloc[-2:-1]  # Use the last CLOSED bar to avoid repainting
        
        # 1. Regime Detection (HMM)
        regime_features = latest[['return', 'volatility']].values
        regime_state = self.hmm.predict(regime_features)[0]
        current_regime = "trend" if regime_state == 0 else "range"
        
        # 2. Primary Signal (LightGBM)
        tree_features = latest[self.feature_cols]
        tree_probas = self.tree.predict(tree_features)[0]
        
        primary_signal = 0
        if current_regime == "trend":
            predicted_class = np.argmax(tree_probas)
            primary_signal = -1 if predicted_class == 0 else (1 if predicted_class == 2 else 0)
        
        # 3. Meta-Learner Confidence Filter
        p_correct = 0.0
        if primary_signal != 0:
            meta_features = pd.DataFrame({
                'primary_signal': [primary_signal],
                'regime_trend': [1 if current_regime == 'trend' else 0],
                'volatility': latest['volatility'].values
            })
            p_correct = self.meta.predict_proba(meta_features)[0][1]
        
        # 4. Apply confidence threshold
        final_signal = primary_signal if p_correct >= self.confidence_threshold else 0
        
        return final_signal, p_correct, current_regime
    
    def execute_cycle(self):
        """
        Main trading cycle for this symbol — เทรดจาก THOR
        Called every H4 candle.
        """
        logger.info(f"[{self.symbol}] --- THOR Cycle Start ---")
        
        mt5.symbol_select(self.symbol, True)
        
        # 1. Fetch data
        rates = mt5.copy_rates_from_pos(self.symbol, self.config['timeframe'], 0, 50)
        if rates is None or len(rates) < 30:
            logger.error(f"[{self.symbol}] Not enough bars. Skipping.")
            return
        
        df = pd.DataFrame(rates)
        df['time'] = pd.to_datetime(df['time'], unit='s')
        df.set_index('time', inplace=True)
        
        # 2. Compute features & predict
        df = self._compute_features(df)
        final_signal, confidence, regime = self._predict(df)
        
        signal_name = {1: 'LONG', -1: 'SHORT', 0: 'FLAT'}
        logger.info(f"[{self.symbol}] Signal={signal_name[final_signal]} | "
                    f"Conf={confidence:.1%} | Regime={regime} | "
                    f"Threshold={self.confidence_threshold:.4f}")
        
        # 3. Position management
        positions = mt5.positions_get(symbol=self.symbol)
        has_position = positions is not None and len(positions) > 0
        
        if has_position:
            pos = positions[0]
            current_dir = 1 if pos.type == mt5.ORDER_TYPE_BUY else -1
            
            if final_signal == 0:
                logger.info(f"[{self.symbol}] Signal FLAT → Closing position #{pos.ticket}")
                self._close_position(pos.ticket)
                return
            elif final_signal == current_dir:
                logger.info(f"[{self.symbol}] Signal aligns → Holding position #{pos.ticket}")
                return
            else:
                logger.info(f"[{self.symbol}] Signal flipped → Closing #{pos.ticket} before reversing")
                self._close_position(pos.ticket)
                # Fall through to open new position
        else:
            if final_signal == 0:
                logger.info(f"[{self.symbol}] No signal, no position. Standing by.")
                return
        
        # 4. Pre-trade safety checks — เทรดจาก THOR
        if not self.guards.is_safe_to_trade(self.symbol):
            logger.warning(f"[{self.symbol}] Trade blocked by Execution Guards.")
            return
        
        # 5. Dynamic Lot Sizing — เทรดจาก THOR
        account = mt5.account_info()
        equity = account.equity if account else 300.0
        lot_size = self._calculate_dynamic_lot(equity)
        
        if lot_size <= 0:
            logger.warning(f"[{self.symbol}] Lot size is 0. Trade skipped.")
            return
        
        # 6. Calculate SL/TP from ATR
        current_atr = df['atr'].iloc[-2]
        point = mt5.symbol_info(self.symbol).point
        sl_points = int((current_atr * self.sl_multiplier) / point)
        tp_points = int((current_atr * self.tp_multiplier) / point)
        
        # 7. Send order — เทรดจาก THOR
        direction_str = 'BUY' if final_signal == 1 else 'SELL'
        logger.info(f"[{self.symbol}] >>> THOR SENDING {direction_str} {lot_size} lots "
                    f"(SL={sl_points}pts, TP={tp_points}pts) <<<")
        
        result = self._send_order(final_signal, lot_size, sl_points, tp_points)
        
        if result and result.get('retcode') == mt5.TRADE_RETCODE_DONE:
            logger.info(f"[{self.symbol}] [OK] THOR Order filled! Ticket: {result.get('order')}")
        else:
            logger.error(f"[{self.symbol}] [FAIL] THOR Order failed: {result}")
    
    def _send_order(self, direction: int, lot_size: float, sl_points: int, tp_points: int):
        """Send market order with THOR comment — เทรดจาก THOR"""
        symbol_info = mt5.symbol_info(self.symbol)
        if symbol_info is None:
            return None
        
        point = symbol_info.point
        digits = symbol_info.digits
        
        if direction == 1:
            order_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(self.symbol).ask
            sl = round(price - (sl_points * point), digits)
            tp = round(price + (tp_points * point), digits)
        else:
            order_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(self.symbol).bid
            sl = round(price + (sl_points * point), digits)
            tp = round(price - (tp_points * point), digits)
        
        price = round(price, digits)
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": float(lot_size),
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": self.config['slippage_points'],
            "magic": self.config['magic_number'],
            "comment": "THOR",  # เทรดจาก THOR
            "type_time": mt5.ORDER_TIME_GTC,
        }
        
        filling_modes = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        for fill_mode in filling_modes:
            request["type_filling"] = fill_mode
            result = mt5.order_send(request)
            if result is None:
                continue
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                return result._asdict()
            elif result.retcode == mt5.TRADE_RETCODE_INVALID_FILL:
                continue
            else:
                return result._asdict()
        
        return None
    
    def _close_position(self, ticket: int):
        """Close position with THOR comment — เทรดจาก THOR"""
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            return
        
        pos = position[0]
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = (mt5.symbol_info_tick(self.symbol).bid 
                 if close_type == mt5.ORDER_TYPE_SELL 
                 else mt5.symbol_info_tick(self.symbol).ask)
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": self.symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": self.config['slippage_points'],
            "magic": self.config['magic_number'],
            "comment": "THOR-Close",  # เทรดจาก THOR (ปิดออเดอร์)
            "type_time": mt5.ORDER_TIME_GTC,
        }
        
        filling_modes = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        for fill_mode in filling_modes:
            request["type_filling"] = fill_mode
            result = mt5.order_send(request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                logger.info(f"[{self.symbol}] Closed position #{ticket} — เทรดจาก THOR")
                return


# ============================================================
# ThorDaemon — Main Trading Loop (เทรดจาก THOR)
# ============================================================
class ThorDaemon:
    """
    เทรดจาก THOR — Main daemon that orchestrates
    multi-symbol live trading on H4 timeframe.
    """
    
    def __init__(self, config: dict = THOR_CONFIG):
        self.config = config
        self.traders = {}
        
    def initialize(self):
        """Connect to MT5 and load all symbol traders — เทรดจาก THOR"""
        logger.info("=" * 60)
        logger.info("   THOR AI LIVE TRADING SYSTEM")
        logger.info("   Trade by THOR - Automated ML Trading")
        logger.info("=" * 60)
        logger.info(f"Symbols : {', '.join(self.config['symbols'])}")
        logger.info(f"Lot Rule: {self.config['lot_per_100']} lot per $100 equity")
        logger.info(f"Magic   : {self.config['magic_number']}")
        logger.info(f"Comment : {self.config['order_comment']}")
        logger.info("=" * 60)
        
        if not mt5_client.connect():
            raise ConnectionError("[THOR] Failed to connect to MT5 terminal!")
        
        account = mt5.account_info()
        if account:
            logger.info(f"Account : {account.login} | Balance: ${account.balance:.2f} | "
                        f"Equity: ${account.equity:.2f}")
        
        for symbol in self.config['symbols']:
            self.traders[symbol] = ThorSymbolTrader(symbol, self.config)
            
        logger.info(f"[THOR] All {len(self.traders)} traders initialized. Ready to trade.")
    
    def run_all_cycles(self):
        """Execute one trading cycle for all symbols — เทรดจาก THOR"""
        logger.info(f"\n{'=' * 60}")
        logger.info(f"[THOR] Trading cycle at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        logger.info(f"{'=' * 60}")
        
        for symbol, trader in self.traders.items():
            try:
                trader.execute_cycle()
            except Exception as e:
                logger.error(f"[{symbol}] THOR cycle error: {e}", exc_info=True)
        
        # Log portfolio summary
        account = mt5.account_info()
        if account:
            logger.info(f"\n[THOR] Portfolio Summary: "
                        f"Balance=${account.balance:.2f} | "
                        f"Equity=${account.equity:.2f} | "
                        f"Margin=${account.margin:.2f} | "
                        f"Free=${account.margin_free:.2f}")
        
        positions = mt5.positions_get()
        if positions:
            logger.info(f"[THOR] Open positions: {len(positions)}")
            for p in positions:
                logger.info(f"  #{p.ticket} {p.symbol} {'BUY' if p.type==0 else 'SELL'} "
                            f"{p.volume}lots P/L=${p.profit:.2f}")
        else:
            logger.info("[THOR] No open positions.")
    
    def run_once(self):
        """Run a single cycle (for testing) — เทรดจาก THOR"""
        self.initialize()
        self.run_all_cycles()
        logger.info("[THOR] Single cycle complete.")
    
    def run_forever(self):
        """
        Run continuously on H4 schedule — เทรดจาก THOR
        Wakes up at every H4 candle boundary (00:00, 04:00, 08:00, 12:00, 16:00, 20:00 UTC)
        """
        self.initialize()
        logger.info("[THOR] Starting infinite daemon loop (H4 schedule)...")
        
        while True:
            try:
                self.run_all_cycles()
            except Exception as e:
                logger.error(f"[THOR] Critical error in cycle: {e}", exc_info=True)
            
            # Calculate sleep until next H4 candle
            now = datetime.utcnow()
            current_h4_block = now.hour // 4
            next_h4_hour = (current_h4_block + 1) * 4
            
            if next_h4_hour >= 24:
                next_wakeup = now.replace(hour=0, minute=1, second=0, microsecond=0) + timedelta(days=1)
            else:
                next_wakeup = now.replace(hour=next_h4_hour, minute=1, second=0, microsecond=0)
            
            sleep_seconds = (next_wakeup - now).total_seconds()
            
            if sleep_seconds < 0:
                sleep_seconds = 60  # Fallback
            
            logger.info(f"[THOR] Next cycle at {next_wakeup.strftime('%H:%M UTC')} "
                        f"(sleeping {sleep_seconds/60:.0f} minutes)")
            time.sleep(sleep_seconds)


# ============================================================
# Entry Point — เทรดจาก THOR
# ============================================================
if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(
        description="🔱 THOR AI Live Trading System — เทรดจาก THOR"
    )
    parser.add_argument(
        '--mode', type=str, default='once',
        choices=['once', 'live'],
        help="'once' = single cycle (test), 'live' = continuous H4 daemon"
    )
    args = parser.parse_args()
    
    daemon = ThorDaemon(config=THOR_CONFIG)
    
    if args.mode == 'live':
        # เทรดจาก THOR — Production Mode
        daemon.run_forever()
    else:
        # เทรดจาก THOR — Test Mode (single cycle)
        daemon.run_once()
