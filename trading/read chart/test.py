import MetaTrader5 as mt5
from telethon import TelegramClient, events
import re
import math
import asyncio  

# --- Telegram Configuration ---
API_ID = 38573096          
API_HASH = 'e5303c2a79ac4e7af4a21489238c0123'
CHANNEL_USERNAME = 'abo_slutan'  

# --- MT5 Terminals Configuration ---
# ضع هنا مسارات المنصات التي قمت بتثبيتها وتعمل حاليا على جهازك
TERMINAL_PATHS = [
    r"D:\mt5\zaid Demo mt5\terminal64.exe", 
    r"D:\mt5\MUSTAFA DEMO\terminal64.exe",
    r"D:\mt5\yousef demo\terminal64.exe"  
]

TARGET_RISK_PERCENT = 0.02 # المخاطرة المستهدفة 2%
MAX_RISK_PERCENT = 0.05    # الحد الأقصى المسموح للمخاطرة 5%

# --- Symbol Mapping ---
# قاموس تحويل الأسماء من تيليجرام إلى رموز المنصة
# يمكنك إضافة أي أزواج أخرى هنا في المستقبل
SYMBOL_MAP = {
    "PALLADIUM": "XPDUSD"
}

# دالة حساب اللوت بناء على المخاطرة
def calculate_lot_size(symbol, entry_price, sl_price):
    account_info = mt5.account_info()
    if account_info is None:
        return 0.0

    balance = account_info.balance
    target_risk_amount = balance * TARGET_RISK_PERCENT

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        return 0.0

    tick_value = symbol_info.trade_tick_value
    tick_size = symbol_info.trade_tick_size

    if tick_value == 0 or tick_size == 0:
        return 0.0

    points_at_risk = abs(entry_price - sl_price) / tick_size
    if points_at_risk == 0:
        return 0.0

    raw_lot_size = target_risk_amount / (points_at_risk * tick_value)
    
    step = symbol_info.volume_step
    min_lot = symbol_info.volume_min
    max_lot = symbol_info.volume_max

    lot_size = math.floor(raw_lot_size / step) * step

    if lot_size < min_lot:
        lot_size = min_lot
        print(f"Calculated lot is less than min lot. Testing min lot {min_lot} for risk limit...")

    # التحقق من عدم تجاوز المخاطرة 5%
    actual_risk_amount = lot_size * points_at_risk * tick_value
    actual_risk_percent = actual_risk_amount / balance

    if actual_risk_percent > MAX_RISK_PERCENT:
        print(f"CRITICAL: Trade risk is {(actual_risk_percent*100):.2f}%, which exceeds the 5% limit!")
        return -1.0 

    if lot_size > max_lot:
        lot_size = max_lot

    return round(lot_size, 2)

# دالة وضع الأوامر وتحديثها
def place_trade(action, symbol, entry_price, sl, tp):
    # إضافة علامة التعجب للرمز فقط إذا لم يكن ينتهي بـ ! أو #
    if not symbol.endswith('!') and not symbol.endswith('#'):
        symbol = symbol + '!'

    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None:
        print("Symbol not found on MT5:", symbol)
        return

    if not symbol_info.visible:
        if not mt5.symbol_select(symbol, True):
            print("Failed to select symbol in Market Watch:", symbol)
            return

    # 1. فحص الصفقات المفعلة حاليا 
    positions = mt5.positions_get(symbol=symbol)
    if positions is not None and len(positions) > 0:
        print(f"Active position already exists for {symbol}. Skipping new signal to prevent double risk.")
        return

    # 2. فحص الأوامر المعلقة القديمة وحذفها
    existing_orders = mt5.orders_get(symbol=symbol)
    if existing_orders is not None and len(existing_orders) > 0:
        print(f"Updating existing pending orders for {symbol}...")
        for order in existing_orders:
            cancel_request = {
                "action": mt5.TRADE_ACTION_REMOVE,
                "order": order.ticket
            }
            result = mt5.order_send(cancel_request)
            if result.retcode == mt5.TRADE_RETCODE_DONE:
                print(f"Old pending order removed successfully (Ticket: {order.ticket}).")
            else:
                print(f"Failed to remove old order! Retcode: {result.retcode}. Aborting to prevent duplicate orders.")
                return

    # جلب السعر الحالي للسوق
    tick = mt5.symbol_info_tick(symbol)
    if tick is None:
        print("Failed to get market price for", symbol)
        return

    # 3. طباعة الأسعار لمراقبة مشاكل التنفيذ
    print(f"Current Market Price -> Ask: {tick.ask} | Bid: {tick.bid}")
    print(f"Target Entry Price -> {entry_price}")

    # تحديد نوع الأمر بناء على السعر
    if action == 'BUY':
        if entry_price < tick.ask:
            order_type = mt5.ORDER_TYPE_BUY_LIMIT
            order_name = "BUY LIMIT"
        else:
            order_type = mt5.ORDER_TYPE_BUY_STOP
            order_name = "BUY STOP"
    elif action == 'SELL':
        if entry_price > tick.bid:
            order_type = mt5.ORDER_TYPE_SELL_LIMIT
            order_name = "SELL LIMIT"
        else:
            order_type = mt5.ORDER_TYPE_SELL_STOP
            order_name = "SELL STOP"
    else:
        print("Unknown action:", action)
        return

    # حساب اللوت
    lot = calculate_lot_size(symbol, entry_price, sl)
    if lot == -1.0:
        print("Trade aborted for this account due to high risk (>5%).")
        return
    elif lot <= 0:
        print("Invalid lot size calculated. Trade aborted.")
        return

    print(f"Preparing {order_name}: {lot} lots of {symbol} at {entry_price} | SL: {sl} | TP: {tp}")

    # إرسال الأمر للسيرفر
    request = {
        "action": mt5.TRADE_ACTION_PENDING, 
        "symbol": symbol,
        "volume": lot,
        "type": order_type,
        "price": entry_price, 
        "sl": float(sl),
        "tp": float(tp),
        "deviation": 20,
        "magic": 999999,
        "comment": "TG Pending Signal",
        "type_time": mt5.ORDER_TIME_GTC, 
    }

    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print("Order send failed, retcode:", result.retcode)
        print("Error details:", result.comment) 
    else:
        print("Pending order placed successfully! Ticket number:", result.order)

# دالة قراءة التوصية
def parse_signal(message_text):
    symbol_match = re.search(r'\]\s*([A-Za-z0-9\/]+)\s*\-', message_text)
    action_match = re.search(r'\-\s*(صاعد|هابط)\s*\-', message_text)
    entry_match = re.search(r'عند مستوى\s*([\d\.]+)', message_text)
    sl_match = re.search(r'وقف الخسارة:\s*([\d\.]+)', message_text)
    tp_match = re.search(r'المستهدف السعري 1:\s*([\d\.]+)', message_text)
    
    if symbol_match and action_match and entry_match and sl_match and tp_match:
        raw_symbol = symbol_match.group(1).replace('/', '').upper()
        
        # ترجمة اسم الزوج إذا كان موجودا في القاموس
        if raw_symbol in SYMBOL_MAP:
            raw_symbol = SYMBOL_MAP[raw_symbol]
            
        direction_ar = action_match.group(1)
        action = 'BUY' if direction_ar == 'صاعد' else 'SELL'
        
        entry_price = float(entry_match.group(1).strip('.'))
        sl = float(sl_match.group(1).strip('.'))
        tp = float(tp_match.group(1).strip('.'))
        
        return action, raw_symbol, entry_price, sl, tp 
    
    return None

client = TelegramClient('mt5_trading_session', API_ID, API_HASH)

@client.on(events.NewMessage(chats=CHANNEL_USERNAME))
async def my_event_handler(event):
    print("\n--- New Telegram Message Received ---")
    message = event.raw_text
    
    signal_data = parse_signal(message)
    if signal_data:
        action, symbol, entry_price, sl, tp = signal_data
        print(f"Signal Parsed: Action={action}, Symbol={symbol}, Entry={entry_price}, SL={sl}, TP={tp}")
        
        for path in TERMINAL_PATHS:
            print(f"\n[>>>] Connecting to MT5 Terminal at: {path} [<<<]")
            
            is_initialized = mt5.initialize(path=path)
            
            if not is_initialized:
                print(f"Failed to connect to terminal. Error code: {mt5.last_error()}")
                continue
                
            account_info = mt5.account_info()
            if account_info is None:
                print("Terminal connected, but no account is logged in manually! Skipping...")
                continue
                
            print(f"Active Account Found: {account_info.login} | Balance: {account_info.balance}")
            
            place_trade(action, symbol, entry_price, sl, tp)
            
    else:
        print("Message does not match standard signal format. Ignored.")

async def main():
    print("Starting Telegram listener...")
    await client.start()
    print("Listening for new signals. Press Ctrl+C to stop.")
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBot stopped by user.")