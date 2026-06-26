import sys
import os
from unittest.mock import MagicMock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# We must mock MetaTrader5 BEFORE importing the modules that rely on it
import MetaTrader5 as mt5_mock
sys.modules['MetaTrader5'] = mt5_mock

from src.layers.l7_execution.guards import ExecutionGuards
from src.layers.l7_execution.order_manager import OrderManager

def test_l7_execution():
    print("Testing L7 Execution (Mocked)...")
    
    symbol = "EURUSD"
    
    # 1. Test Guards (Spread block)
    guards = ExecutionGuards(max_spread_points=20)
    
    # Mock wide spread (30 points)
    mock_info_wide = MagicMock()
    mock_info_wide.spread = 30
    mt5_mock.symbol_info = MagicMock(return_value=mock_info_wide)
    
    is_safe = guards.is_safe_to_trade(symbol)
    print(f"Safety check with 30-point spread (limit 20): {'Safe' if is_safe else 'Blocked'}")
    assert not is_safe, "Spread guard failed to block trade."
    
    # Mock tight spread (10 points)
    mock_info_tight = MagicMock()
    mock_info_tight.spread = 10
    mt5_mock.symbol_info = MagicMock(return_value=mock_info_tight)
    
    is_safe = guards.is_safe_to_trade(symbol)
    print(f"Safety check with 10-point spread (limit 20): {'Safe' if is_safe else 'Blocked'}")
    assert is_safe, "Spread guard blocked a valid trade."
    
    # 2. Test Order Manager Payload formatting
    manager = OrderManager(magic_number=999, slippage_points=5)
    
    # Setup mocks for order_send
    mock_info_tight.visible = True
    mock_info_tight.point = 0.00001
    
    mock_tick = MagicMock()
    mock_tick.ask = 1.10000
    mock_tick.bid = 1.09990
    mt5_mock.symbol_info_tick = MagicMock(return_value=mock_tick)
    
    # Setup constants
    mt5_mock.ORDER_TYPE_BUY = 0
    mt5_mock.ORDER_TYPE_SELL = 1
    mt5_mock.TRADE_ACTION_DEAL = 1
    mt5_mock.ORDER_TIME_GTC = 0
    mt5_mock.ORDER_FILLING_IOC = 1
    mt5_mock.TRADE_RETCODE_DONE = 10009
    
    # Mock result
    mock_result = MagicMock()
    mock_result.retcode = 10009
    mock_result.order = 12345
    mock_result._asdict.return_value = {"retcode": 10009, "order": 12345}
    mt5_mock.order_send = MagicMock(return_value=mock_result)
    
    # Send Long
    res = manager.send_market_order(symbol, direction=1, lot_size=1.0, sl_points=100, tp_points=200)
    
    # Verify the payload passed to order_send
    call_args = mt5_mock.order_send.call_args[0][0]
    
    print("\nSimulated Order Payload (Long):")
    for k, v in call_args.items():
        print(f"  {k}: {v}")
        
    assert call_args['symbol'] == "EURUSD"
    assert call_args['type'] == mt5_mock.ORDER_TYPE_BUY
    assert call_args['price'] == 1.10000 # Ask price
    assert round(call_args['sl'], 5) == 1.09900 # 1.10000 - (100 * 0.00001)
    assert round(call_args['tp'], 5) == 1.10200 # 1.10000 + (200 * 0.00001)
    assert call_args['magic'] == 999
    
    print("\nL7 Execution Test Passed.")

if __name__ == "__main__":
    test_l7_execution()
