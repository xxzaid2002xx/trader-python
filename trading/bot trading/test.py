import MetaTrader5 as mt5
from telethon import TelegramClient, events
import re
import math
import asyncio
import time
from datetime import datetime

# ============================================================
# 1. Telegram Configuration
# ============================================================
API_ID = 38573096          
API_HASH = 'e5303c2a79ac4e7af4a21489238c0123'
CHANNEL_USERNAME = 'abo_slutan'  

# ============================================================
# 2. Terminals Configuration
# ============================================================
MASTER_TERMINAL = r"D:\mt5\MASTER\terminal64.exe"

SLAVE_TERMINALS = [
    r"D:\mt5\Demo account\ali abdulla demo\terminal64.exe",
    r"D:\mt5\Demo account\mahdi abdullah demo\terminal64.exe",
    r"D:\mt5\Demo account\mustafa demo\terminal64.exe"
]

# ============================================================
# 3. Risk Management & Filters
# ============================================================
TARGET_RISK_PERCENT = 0.02 
MAX_RISK_PERCENT = 0.06    

MAGIC_NUMBER = 999111
SLIPPAGE = 50
FILLING_TYPE = mt5.ORDER_FILLING_IOC
MAX_PIPS_DIFFERENCE = 50  

SYMBOL_MAP = {
    "PALLADIUM": "XPDUSD", "XPDUSD": "XPDUSD", "BRENT": "BRNUSD",
    "BRNUSD": "BRNUSD", "GOLD": "XAUUSD", "XAUUSD": "XAUUSD",
    "XAGUSD": "XAGUSD", "USOIL": "WTIUSD", "CL.1": "WTIUSD", 
    "WTI": "WTIUSD", "USDJPY": "USDJPY", "BTCUSD": "BTCUSD"
}

COPIED_POSITIONS = {path: {} for path in SLAVE_TERMINALS}
KNOWN_MASTER_POSITIONS = set()
WARNING_MEMORY = set() # ذاكرة لمنع تكرار طباعة نفس الخطأ كل 3 ثوانٍ
mt5_lock = asyncio.Lock()

# ============================================================
# 4. Helper Functions
# ============================================================
def get_active_symbol(raw_symbol):
    clean_name = raw_symbol.replace("!", "").replace("#", "").split('.')[0]
    suffixes = ["", "!", "#", ".m", "m", "c", ".c", "pro"]
    for s in suffixes:
        sym = clean_name + s
        if mt5.symbol_info(sym) is not None:
            return sym
    return clean_name + "!"

def calculate_pip_difference(symbol, price1, price2):
    info = mt5.symbol_info(symbol)
    if info is None: return 0
    point = info.point
    digits = info.digits
    pip_value = point * 10 if digits in (3, 5) else point
    return abs(price1 - price2) / pip_value

def calculate_dynamic_lot_size(symbol, entry_price, sl_price, balance, account_name="Unknown"):
    if sl_price == 0 or entry_price == sl_price: return 0.0
    info = mt5.symbol_info(symbol)
    if info is None: return 0.0

    tick_size = info.trade_tick_size
    tick_value = info.trade_tick_value
    if tick_size == 0 or tick_value == 0: return 0.0

    ticks_at_risk = abs(entry_price - sl_price) / tick_size
    risk_for_one_lot = ticks_at_risk * tick_value
    if risk_for_one_lot == 0: return 0.0

    target_risk_amount = balance * TARGET_RISK_PERCENT
    calculated_lot = target_risk_amount / risk_for_one_lot

    min_lot = info.volume_min
    max_lot = info.volume_max
    step = info.volume_step
    if step == 0: step = 0.01

    calculated_lot = math.floor(calculated_lot / step) * step
    if calculated_lot < min_lot: calculated_lot = min_lot

    actual_risk_percent = (calculated_lot * risk_for_one_lot) / balance
    if actual_risk_percent > MAX_RISK_PERCENT:
        print(f"[!] [{datetime.now().strftime('%H:%M:%S')}] [{account_name:<20}] REJECTED: Risk {(actual_risk_percent*100):.1f}% > Max Limit")
        return 0.0 

    if calculated_lot > max_lot: calculated_lot = max_lot
    return round(calculated_lot, 2)

# ============================================================
# 5. Telegram Logic (Master Orders)
# ============================================================
def parse_signal(message_text):
    symbol_match = re.search(r'\]\s*([A-Za-z0-9\.\/]+)\s*\-', message_text)
    action_match = re.search(r'\-\s*(صاعد|هابط)\s*\-', message_text)
    entry_match = re.search(r'عند مستوى[^\d]*([\d\.]+)', message_text)
    sl_match = re.search(r'وقف الخسارة:\s*([\d\.]+)', message_text)
    tp_match = re.search(r'المستهدف السعري 1:\s*([\d\.]+)', message_text)
    
    if symbol_match and action_match and entry_match and sl_match and tp_match:
        raw_symbol = symbol_match.group(1).replace('/', '').upper()
        if raw_symbol in SYMBOL_MAP:
            raw_symbol = SYMBOL_MAP[raw_symbol]
            
        direction_ar = action_match.group(1)
        action = 'BUY' if direction_ar == 'صاعد' else 'SELL'
        entry_price = float(entry_match.group(1).strip('.'))
        sl = float(sl_match.group(1).strip('.'))
        tp = float(tp_match.group(1).strip('.'))
        
        return action, raw_symbol, entry_price, sl, tp 
    return None

def place_master_trade(action, raw_symbol, entry_price, sl, tp):
    current_time = datetime.now().strftime('%H:%M:%S')
    print(f"\n---> NEW TELEGRAM SIGNAL: {action} {raw_symbol} @ {entry_price} <---")
    
    if not mt5.initialize(path=MASTER_TERMINAL): return

    account_info = mt5.account_info()
    if account_info is None: return

    symbol = get_active_symbol(raw_symbol)
    symbol_info = mt5.symbol_info(symbol)
    if symbol_info is None: return

    if not symbol_info.visible:
        mt5.symbol_select(symbol, True)
        time.sleep(1)

    positions = mt5.positions_get(symbol=symbol)
    if positions is not None and len(positions) > 0:
        print(f"[!] [{current_time}] [MASTER              ] SKIPPED: Active position already exists.")
        return

    existing_orders = mt5.orders_get(symbol=symbol)
    if existing_orders is not None and len(existing_orders) > 0:
        for order in existing_orders:
            mt5.order_send({"action": mt5.TRADE_ACTION_REMOVE, "order": order.ticket})

    tick = mt5.symbol_info_tick(symbol)
    retries = 0
    while (tick is None or tick.ask == 0.0 or tick.bid == 0.0) and retries < 5:
        time.sleep(1.0)
        tick = mt5.symbol_info_tick(symbol)
        retries += 1

    if tick is None or tick.ask == 0.0 or tick.bid == 0.0: return

    lot_size = calculate_dynamic_lot_size(symbol, entry_price, sl, account_info.balance, "MASTER")
    if lot_size == 0.0: return

    if action == 'BUY':
        order_type = mt5.ORDER_TYPE_BUY_LIMIT if entry_price < tick.ask else mt5.ORDER_TYPE_BUY_STOP
    else:
        order_type = mt5.ORDER_TYPE_SELL_LIMIT if entry_price > tick.bid else mt5.ORDER_TYPE_SELL_STOP

    request = {
        "action": mt5.TRADE_ACTION_PENDING, "symbol": symbol, "volume": lot_size,
        "type": order_type, "price": entry_price, "sl": float(sl), "tp": float(tp),
        "deviation": 20, "magic": 999999, "comment": "TG Master Signal",
        "type_time": mt5.ORDER_TIME_GTC, 
    }

    result = mt5.order_send(request)
    if result.retcode == mt5.TRADE_RETCODE_DONE:
        print(f"[+] [{current_time}] [MASTER              ] PENDING ORDER PLACED -> Ticket: {result.order}")

client = TelegramClient('mt5_trading_session', API_ID, API_HASH)

@client.on(events.NewMessage(chats=CHANNEL_USERNAME))
async def telegram_handler(event):
    signal_data = parse_signal(event.raw_text)
    if signal_data:
        action, raw_symbol, entry_price, sl, tp = signal_data
        async with mt5_lock:
            place_master_trade(action, raw_symbol, entry_price, sl, tp)

# ============================================================
# 6. Copier & Synchronization Logic
# ============================================================
def sync_terminals(current_time):
    global KNOWN_MASTER_POSITIONS
    
    if not mt5.initialize(path=MASTER_TERMINAL): return
    time.sleep(0.05) # إعطاء المنصة جزء من الثانية للتحديث
    
    master_positions = mt5.positions_get()
    # إذا فشل جلب الصفقات بسبب انقطاع اتصال مؤقت، نخرج من الدالة ولا نمسح الذاكرة
    if master_positions is None: return 
    
    master_dict = {p.ticket: p for p in master_positions}
    current_master_tickets = set(master_dict.keys())
    
    # --- مراقبة وتنبيه عند تفعيل صفقة في الماستر ---
    new_master_tickets = current_master_tickets - KNOWN_MASTER_POSITIONS
    for tkt in new_master_tickets:
        m_pos = master_dict[tkt]
        trade_type = "BUY" if m_pos.type == mt5.ORDER_TYPE_BUY else "SELL"
        print(f"[>] [{current_time}] [MASTER              ] ACTIVE TRADE TRIGGERED -> {m_pos.symbol} | {trade_type} | Lot: {m_pos.volume} | Ticket: {tkt}")
    
    KNOWN_MASTER_POSITIONS = current_master_tickets
    # -----------------------------------------------

    for slave_path in SLAVE_TERMINALS:
        slave_name = slave_path.split('\\')[-2] 
        
        if not mt5.initialize(path=slave_path): continue
        time.sleep(0.05)
            
        acc_info = mt5.account_info()
        if not acc_info: continue
            
        slave_balance = acc_info.balance
        slave_positions = mt5.positions_get()
        slave_dict = {p.ticket: p for p in slave_positions} if slave_positions else {}
        
        copied_map = COPIED_POSITIONS[slave_path]

        for s_tkt, s_pos in slave_dict.items():
            if s_pos.comment and s_pos.comment.startswith("Copied "):
                try:
                    m_tkt = int(s_pos.comment.split(" ")[1])
                    if m_tkt not in copied_map:
                        copied_map[m_tkt] = s_tkt
                        print(f"[*] [{current_time}] [{slave_name:<20}] MEMORY RECOVERED -> Master: {m_tkt} | Slave: {s_tkt}")
                except Exception:
                    pass
        
        # A. الإغلاق المتزامن
        for m_tkt in list(copied_map.keys()):
            if m_tkt not in master_dict:
                s_tkt = copied_map[m_tkt]
                if s_tkt != -1 and s_tkt in slave_dict:
                    pos = slave_dict[s_tkt]
                    close_type = mt5.ORDER_TYPE_BUY if pos.type == mt5.ORDER_TYPE_SELL else mt5.ORDER_TYPE_SELL
                    
                    mt5.symbol_select(pos.symbol, True)
                    tick = mt5.symbol_info_tick(pos.symbol)
                    if tick:
                        price = tick.ask if close_type == mt5.ORDER_TYPE_BUY else tick.bid
                        req = {
                            "action": mt5.TRADE_ACTION_DEAL, "symbol": pos.symbol,
                            "volume": pos.volume, "type": close_type, "position": s_tkt,
                            "price": price, "deviation": SLIPPAGE, "magic": MAGIC_NUMBER,
                            "type_time": mt5.ORDER_TIME_GTC, "type_filling": FILLING_TYPE,
                        }
                        res = mt5.order_send(req)
                        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                            print(f"[-] [{current_time}] [{slave_name:<20}] MASTER CLOSED -> Closed Ticket: {s_tkt}")
                            del copied_map[m_tkt]
                        else:
                            error_code = res.retcode if res else "No Response"
                            print(f"[!] [{current_time}] [{slave_name:<20}] FAILED TO CLOSE -> Ticket: {s_tkt} | Error: {error_code}")
                else:
                    del copied_map[m_tkt]

        # B. نسخ الصفقات الجديدة ومراقبة الأخطاء الصامتة
        for m_tkt, m_pos in master_dict.items():
            if m_tkt not in copied_map:
                real_symbol = get_active_symbol(m_pos.symbol)
                mt5.symbol_select(real_symbol, True)
                tick = mt5.symbol_info_tick(real_symbol)
                
                # 1. كشف خطأ الرمز أو توقف السوق
                if not tick or tick.ask == 0.0:
                    warn_key = f"{slave_name}_{m_tkt}_tick"
                    if warn_key not in WARNING_MEMORY:
                        print(f"[!] [{current_time}] [{slave_name:<20}] ERROR: Cannot read price for {real_symbol}. Check Market Watch.")
                        WARNING_MEMORY.add(warn_key)
                    continue
                
                curr_price = tick.ask if m_pos.type == 0 else tick.bid
                diff = calculate_pip_difference(real_symbol, m_pos.price_open, curr_price)
                
                if diff > MAX_PIPS_DIFFERENCE: 
                    print(f"[*] [{current_time}] [{slave_name:<20}] SKIPPED OLD TRADE -> {real_symbol} (Diff: {diff:.1f} pips > Limit: {MAX_PIPS_DIFFERENCE})")
                    copied_map[m_tkt] = -1
                    continue
                
                # 2. كشف خطأ "لا يوجد وقف خسارة"
                if m_pos.sl == 0.0:
                    warn_key = f"{slave_name}_{m_tkt}_nosl"
                    if warn_key not in WARNING_MEMORY:
                        print(f"[!] [{current_time}] [{slave_name:<20}] SKIPPED COPY: Master Trade ({m_tkt}) has NO Stop Loss (SL=0).")
                        WARNING_MEMORY.add(warn_key)
                    continue

                trade_lot = calculate_dynamic_lot_size(real_symbol, curr_price, m_pos.sl, slave_balance, slave_name)
                
                # 3. كشف خطأ حجم اللوت
                if trade_lot == 0.0: 
                    warn_key = f"{slave_name}_{m_tkt}_lot"
                    if warn_key not in WARNING_MEMORY:
                        print(f"[!] [{current_time}] [{slave_name:<20}] SKIPPED COPY: Lot calculation resulted in 0.0 (Risk too high).")
                        WARNING_MEMORY.add(warn_key)
                    continue
                
                req = {
                    "action": mt5.TRADE_ACTION_DEAL, "symbol": real_symbol, "volume": trade_lot,
                    "type": m_pos.type, "price": curr_price, "sl": float(m_pos.sl),
                    "tp": float(m_pos.tp), "magic": MAGIC_NUMBER, "deviation": SLIPPAGE,
                    "comment": f"Copied {m_tkt}", "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": FILLING_TYPE,
                }
                res = mt5.order_send(req)
                
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    copied_map[m_tkt] = res.order
                    print(f"[+] [{current_time}] [{slave_name:<20}] NEW TRADE -> {real_symbol} | Lot: {trade_lot} | Ticket: {res.order}")
                else:
                    error_code = res.retcode if res else "No Response"
                    print(f"[!] [{current_time}] [{slave_name:<20}] FAILED TO OPEN -> {real_symbol} | Error Code: {error_code}")
            
            # C. تحديث الأهداف ووقف الخسارة
            else:
                s_tkt = copied_map[m_tkt]
                if s_tkt == -1: continue
                
                if s_tkt in slave_dict:
                    s_pos = slave_dict[s_tkt]
                    if abs(s_pos.sl - m_pos.sl) > 0.0001 or abs(s_pos.tp - m_pos.tp) > 0.0001:
                        req_mod = {
                            "action": mt5.TRADE_ACTION_SLTP, "symbol": s_pos.symbol,
                            "position": s_tkt, "sl": float(m_pos.sl), "tp": float(m_pos.tp)
                        }
                        res_mod = mt5.order_send(req_mod)
                        if res_mod and res_mod.retcode == mt5.TRADE_RETCODE_DONE:
                            print(f"[*] [{current_time}] [{slave_name:<20}] MODIFIED SL/TP -> Symbol: {s_pos.symbol}")
                else:
                    copied_map[m_tkt] = -1

async def copier_worker():
    while True:
        current_time = datetime.now().strftime("%H:%M:%S")
        async with mt5_lock:
            sync_terminals(current_time)
        await asyncio.sleep(3)

# ============================================================
# 7. Main Execution
# ============================================================
async def main():
    global KNOWN_MASTER_POSITIONS
    
    print("================================================================")
    print("                  UNIFIED TRADING SYSTEM v2.5                   ")
    print("================================================================")
    print(" LOG LEGEND:")
    print("   [>] Master entered an ACTIVE TRADE.")
    print("   [+] New trade opened/copied or Pending Order placed.")
    print("   [-] Trade closed syncing with Master.")
    print("   [*] Memory Recovered, SL/TP modified or Skipped.")
    print("   [!] Warnings, Missing SL, or API Errors.")
    print("================================================================\n")
    
    print("[i] Checking Connections...")
    if mt5.initialize(path=MASTER_TERMINAL): 
        print("   [OK] Master Terminal")
        mp = mt5.positions_get()
        if mp is not None:
            KNOWN_MASTER_POSITIONS = {p.ticket for p in mp}
    else: 
        print("   [FAIL] Master Terminal")
        
    for path in SLAVE_TERMINALS:
        slave_name = path.split('\\')[-2]
        if mt5.initialize(path=path): print(f"   [OK] Slave: {slave_name}")
        else: print(f"   [FAIL] Slave: {path}")
    print("----------------------------------------------------------------\n")

    await client.start()
    asyncio.create_task(copier_worker())
    
    print("[i] System Running Cleanly. Waiting for Events...\n")
    await client.run_until_disconnected()

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[i] Bot stopped by user.")