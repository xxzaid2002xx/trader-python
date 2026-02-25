import MetaTrader5 as mt5
import pandas as pd
import time
from datetime import datetime

# ============================================================
# Paths and Configuration
# ============================================================
REAL_ACCOUNT_TERMINAL_PATH = r"D:\mt5\zaid Ramdan mt5\terminal64.exe"

# Trading Settings
MAGIC_NUMBER = 999111
SLIPPAGE = 50
FILLING_TYPE = mt5.ORDER_FILLING_IOC

# Risk Management
RISK_PERCENT = 0.02           # Reduced to 2% because trading ALL symbols increases total risk
FALLBACK_LOT = 0.01
RISK_REWARD_RATIO = 2.0
PARTIAL_CLOSE_THRESHOLD = 1.0 
TRAILING_STOP_PIPS = 20.0     

# Strategy Settings
ENTRY_TIMEFRAME = mt5.TIMEFRAME_H1
TREND_TIMEFRAME = mt5.TIMEFRAME_D1
LOOKBACK_PERIOD = 20

# ============================================================
# Dynamic Symbol Management
# ============================================================
def get_all_market_watch_symbols():
    """Fetches all symbols currently visible in the Market Watch window."""
    symbols = mt5.symbols_get()
    # Filter only symbols that are selected in Market Watch
    market_watch_symbols = [s.name for s in symbols if s.select]
    return market_watch_symbols

# ============================================================
# Core Functions
# ============================================================
def get_pip_unit(symbol):
    info = mt5.symbol_info(symbol)
    if info is None: return 0.0001
    return info.point * 10 if info.digits in [3, 5] else info.point

def calculate_lot_size(symbol, entry_price, sl_price, balance):
    if sl_price == 0 or entry_price == sl_price: return FALLBACK_LOT
    info = mt5.symbol_info(symbol)
    if info is None: return FALLBACK_LOT
    
    tick_size = info.trade_tick_size
    tick_value = info.trade_tick_value
    ticks_at_risk = abs(entry_price - sl_price) / tick_size
    risk_for_one_lot = ticks_at_risk * tick_value
    
    if risk_for_one_lot <= 0: return FALLBACK_LOT
    
    risk_amount = balance * RISK_PERCENT
    calculated_lot = round((risk_amount / risk_for_one_lot) / info.volume_step) * info.volume_step
    return max(min(calculated_lot, info.volume_max), info.volume_min)

# ============================================================
# Multi-Timeframe Analysis Engine
# ============================================================
def analyze_market_mtf(symbol):
    # Trend Analysis (Daily SMA 200)
    daily_rates = mt5.copy_rates_from_pos(symbol, TREND_TIMEFRAME, 0, 200)
    if daily_rates is None or len(daily_rates) < 200: return "WAIT", 0.0
    daily_df = pd.DataFrame(daily_rates)
    daily_sma = daily_df['close'].rolling(window=200).mean().iloc[-1]
    daily_close = daily_df['close'].iloc[-1]
    
    # Entry Analysis (H1 Breakout)
    h1_rates = mt5.copy_rates_from_pos(symbol, ENTRY_TIMEFRAME, 0, LOOKBACK_PERIOD + 1)
    if h1_rates is None or len(h1_rates) < LOOKBACK_PERIOD: return "WAIT", 0.0
    h1_df = pd.DataFrame(h1_rates)
    
    resistance = h1_df.iloc[:-1]['high'].max()
    support = h1_df.iloc[:-1]['low'].min()
    h1_close = h1_df['close'].iloc[-1]
    
    if h1_close > resistance and daily_close > daily_sma:
        return "BUY", support
    elif h1_close < support and daily_close < daily_sma:
        return "SELL", resistance
        
    return "WAIT", 0.0

# ============================================================
# Trade Management
# ============================================================
def manage_open_positions():
    positions = mt5.positions_get(magic=MAGIC_NUMBER)
    if not positions: return

    for pos in positions:
        symbol = pos.symbol
        pip_unit = get_pip_unit(symbol)
        tick = mt5.symbol_info_tick(symbol)
        if not tick: continue
        
        entry_price = pos.price_open
        sl_dist = abs(entry_price - pos.sl)
        current_profit_dist = abs(tick.bid - entry_price) if pos.type == 0 else abs(entry_price - tick.ask)
        
        # 1. Partial Close
        if current_profit_dist >= sl_dist * PARTIAL_CLOSE_THRESHOLD and pos.volume > 0.01:
            if "PARTIAL" not in pos.comment:
                close_volume = round((pos.volume / 2) / 0.01) * 0.01
                request = {
                    "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(close_volume),
                    "type": mt5.ORDER_TYPE_SELL if pos.type == 0 else mt5.ORDER_TYPE_BUY,
                    "position": pos.ticket, "price": tick.bid if pos.type == 0 else tick.ask,
                    "comment": "PARTIAL", "type_filling": FILLING_TYPE,
                }
                mt5.order_send(request)

        # 2. Trailing Stop
        trailing_dist = TRAILING_STOP_PIPS * pip_unit
        if pos.type == 0: # Buy
            new_sl = tick.bid - trailing_dist
            if new_sl > pos.sl + pip_unit:
                mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": pos.ticket, "sl": new_sl, "tp": pos.tp})
        else: # Sell
            new_sl = tick.ask + trailing_dist
            if new_sl < pos.sl - pip_unit or pos.sl == 0:
                mt5.order_send({"action": mt5.TRADE_ACTION_SLTP, "position": pos.ticket, "sl": new_sl, "tp": pos.tp})

# ============================================================
# Main Loop
# ============================================================
def main():
    if not mt5.initialize(path=REAL_ACCOUNT_TERMINAL_PATH):
        print("Final initialization failed.")
        return
    
    print("Omni-Market Watch Bot Active (24/7)...")

    try:
        while True:
            manage_open_positions()

            # Dynamically get all symbols from Market Watch
            all_symbols = get_all_market_watch_symbols()
            account = mt5.account_info()

            for symbol in all_symbols:
                # Basic safety: skip if already in a trade for this symbol
                if mt5.positions_get(symbol=symbol, magic=MAGIC_NUMBER): continue
                
                signal, sl_price = analyze_market_mtf(symbol)
                
                if signal != "WAIT":
                    tick = mt5.symbol_info_tick(symbol)
                    if not tick: continue
                    
                    price = tick.ask if signal == "BUY" else tick.bid
                    lot = calculate_lot_size(symbol, price, sl_price, account.balance)
                    tp = price + (abs(price - sl_price) * RISK_REWARD_RATIO) if signal == "BUY" else price - (abs(price - sl_price) * RISK_REWARD_RATIO)
                    
                    request = {
                        "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": float(lot),
                        "type": mt5.ORDER_TYPE_BUY if signal == "BUY" else mt5.ORDER_TYPE_SELL,
                        "price": float(price), "sl": float(sl_price), "tp": float(tp),
                        "magic": MAGIC_NUMBER, "comment": "Omni Entry", "type_filling": FILLING_TYPE,
                    }
                    res = mt5.order_send(request)
                    if res.retcode == mt5.TRADE_RETCODE_DONE:
                        print(f"Opened {signal} on {symbol}")

            time.sleep(15) # Scanning every 15 seconds for fast reactions
    except KeyboardInterrupt:
        mt5.shutdown()

if __name__ == "__main__":
    main()