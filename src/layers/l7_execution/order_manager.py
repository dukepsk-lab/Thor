import MetaTrader5 as mt5
from typing import Optional

class OrderManager:
    """
    Handles the physical transmission of orders to the MetaTrader 5 terminal.
    Includes volume normalization, precision rounding, filling mode fallbacks, and closing capabilities.
    """
    def __init__(self, magic_number: int = 123456, slippage_points: int = 10):
        self.magic_number = magic_number
        self.slippage = slippage_points

    def normalize_volume(self, symbol: str, volume: float) -> float:
        """
        Normalizes the volume to respect MT5 symbol step, min, and max rules.
        """
        symbol_info = mt5.symbol_info(symbol)
        if symbol_info is None:
            return volume
            
        step = symbol_info.volume_step
        min_vol = symbol_info.volume_min
        max_vol = symbol_info.volume_max
        
        # Round to nearest step
        norm_vol = round(volume / step) * step
        
        # Clamp to min and max
        if norm_vol < min_vol:
            norm_vol = min_vol
        elif norm_vol > max_vol:
            norm_vol = max_vol
            
        return round(norm_vol, 2)  # Typically 2 decimals

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
        digits = symbol_info.digits
        
        # Normalize volume
        normalized_lot = self.normalize_volume(symbol, lot_size)
        
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
            
        # Ensure SL/TP are 0 if not provided properly
        if sl_points <= 0: sl = 0.0
        if tp_points <= 0: tp = 0.0

        # Round to correct digits
        price = round(price, digits)
        sl = round(sl, digits)
        tp = round(tp, digits)

        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": float(normalized_lot),
            "type": order_type,
            "price": price,
            "sl": float(sl),
            "tp": float(tp),
            "deviation": self.slippage,
            "magic": self.magic_number,
            "comment": "Thor-ML",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        
        # Try different filling modes to prevent "Invalid Filling" errors
        filling_modes = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        
        for fill_mode in filling_modes:
            request["type_filling"] = fill_mode
            result = mt5.order_send(request)
            
            if result is None:
                continue
                
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"OrderManager: Successfully placed {symbol} order! Ticket: {result.order}")
                return result._asdict()
            elif result.retcode == mt5.TRADE_RETCODE_INVALID_FILL:
                # Try next filling mode
                continue
            else:
                print(f"OrderManager: Trade rejected, retcode: {result.retcode}")
                return result._asdict()
                
        print(f"OrderManager: order_send failed with all filling modes. Last error: {mt5.last_error()}")
        return None

    def close_position(self, ticket: int, symbol: str) -> Optional[dict]:
        """
        Dynamically closes an open position (used when AI says FLAT or FLIP).
        """
        position = mt5.positions_get(ticket=ticket)
        if position is None or len(position) == 0:
            print(f"OrderManager: Ticket {ticket} not found.")
            return None
            
        pos = position[0]
        
        # Reverse the order type to close
        close_type = mt5.ORDER_TYPE_SELL if pos.type == mt5.ORDER_TYPE_BUY else mt5.ORDER_TYPE_BUY
        price = mt5.symbol_info_tick(symbol).bid if close_type == mt5.ORDER_TYPE_SELL else mt5.symbol_info_tick(symbol).ask
        
        request = {
            "action": mt5.TRADE_ACTION_DEAL,
            "symbol": symbol,
            "volume": pos.volume,
            "type": close_type,
            "position": ticket,
            "price": price,
            "deviation": self.slippage,
            "magic": self.magic_number,
            "comment": "Thor-ML Close",
            "type_time": mt5.ORDER_TIME_GTC,
        }
        
        filling_modes = [mt5.ORDER_FILLING_IOC, mt5.ORDER_FILLING_FOK, mt5.ORDER_FILLING_RETURN]
        for fill_mode in filling_modes:
            request["type_filling"] = fill_mode
            result = mt5.order_send(request)
            if result is not None and result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"OrderManager: Closed position {ticket} successfully!")
                return result._asdict()
                
        print(f"OrderManager: Failed to close position {ticket}. Error: {mt5.last_error()}")
        return None
