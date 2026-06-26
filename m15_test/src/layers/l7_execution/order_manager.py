import MetaTrader5 as mt5
from typing import Optional

class OrderManager:
    """
    Handles the physical transmission of orders to the MetaTrader 5 terminal.
    """
    def __init__(self, magic_number: int = 123456, slippage_points: int = 10):
        self.magic_number = magic_number
        self.slippage = slippage_points

    def send_market_order(self, symbol: str, direction: int, lot_size: float, sl_points: int, tp_points: int) -> Optional[dict]:
        """
        Sends a market order.
        direction: 1 for Long (Buy), -1 for Short (Sell)
        """
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            print(f"OrderManager: Symbol {symbol} not found.")
            return None
            
        if not symbol_info.visible:
            mt5.symbol_select(symbol, True)
            
        point = symbol_info.point
        
        # Define order type and calculate prices
        if direction == 1:
            order_type = mt5.ORDER_TYPE_BUY
            price = mt5.symbol_info_tick(symbol).ask
            sl = price - (sl_points * point)
            tp = price + (tp_points * point)
        elif direction == -1:
            order_type = mt5.ORDER_TYPE_SELL
            price = mt5.symbol_info_tick(symbol).bid
            sl = price + (sl_points * point)
            tp = price - (tp_points * point)
        else:
            print("OrderManager: Invalid direction.")
            return None
            
        # Ensure SL/TP are 0 if not provided properly (defensive check)
        if sl_points <= 0: sl = 0.0
        if tp_points <= 0: tp = 0.0

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(lot_size),
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": self.slippage,
            "magic": self.magic_number,
            "comment": "Thor-ML",
            "type_time": mt5.ORDER_TIME_GTC,
            "type_filling": mt5.ORDER_FILLING_IOC, # standard for forex
        }
        
        # Send order
        result = mt5.order_send(request)
        
        if result is None:
            print(f"OrderManager: order_send failed, error code: {mt5.last_error()}")
            return None
            
        if result.retcode != mt5.TRADE_RETCODE_DONE:
            print(f"OrderManager: Trade rejected, retcode: {result.retcode}")
            return result._asdict()
            
        print(f"OrderManager: Successfully placed {symbol} order! Ticket: {result.order}")
        return result._asdict()
