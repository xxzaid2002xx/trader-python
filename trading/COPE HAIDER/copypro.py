import MetaTrader5 as mt5
import time
from datetime import datetime

# ============================================================
# المسارات
# ============================================================
INVESTOR_TERMINAL_PATH = r"D:\mt5\zaid Demo mt5\terminal64.exe"
REAL_ACCOUNT_TERMINAL_PATH = r"D:\mt5\zaidhandred\terminal64.exe"

# ============================================================
# إعدادات التداول وإدارة رأس المال
# ============================================================
MAGIC_NUMBER = 999111
SLIPPAGE = 50
FILLING_TYPE = mt5.ORDER_FILLING_IOC

# الإعدادات الافتراضية للفارق السعري
MAX_PIPS_DIFFERENCE = 500
SAME_PRICE_PIPS = 3.0      

RISK_PERCENT = 0.05        # 5% الحد الأقصى للمخاطرة لكل صفقة

# ============================================================
# المتغيرات العامة وقاموس الرموز
# ============================================================
SYMBOL_MAPPING = {
    "GOLD": "XAUUSD#",     # تحويل الذهب لحالة خاصة مع إضافة #
    "BTCUSD": "BTCUSD#",   # البتكوين مع إضافة #
}

pos_map = {}

# ============================================================
# دوال مساعدة والفلاتر
# ============================================================
def get_cleaned_symbol(raw_symbol):
    if raw_symbol in SYMBOL_MAPPING:
        return SYMBOL_MAPPING[raw_symbol]
    
    clean_name = raw_symbol
    if "." in raw_symbol:
        clean_name = raw_symbol.split('.')[0]
        
    # إزالة أي علامات تعجب أو شباك سابقة لتجنب التكرار
    clean_name = clean_name.replace("!", "").replace("#", "")
        
    # إضافة علامة الشباك (#) الخاصة بحسابك الحقيقي
    return clean_name + "#"

def get_dynamic_thresholds(symbol):
    if "BTC" in symbol:
        return 500000, 2000  
    return MAX_PIPS_DIFFERENCE, SAME_PRICE_PIPS

def calculate_pip_difference(symbol, price1, price2):
    info = mt5.symbol_info(symbol)
    if info is None: return 0
    point = info.point
    digits = info.digits
    pip_value = point * 10 if digits in (3,5) else point
    return abs(price1 - price2) / pip_value

def calculate_lot_size(symbol, entry_price, sl_price, balance):
    # لا يمكن حساب المخاطرة إذا لم يكن هناك ستوب لوس (SL)
    if sl_price == 0 or entry_price == sl_price:
        print(f"⚠️ No SL defined for {symbol}. Cannot calculate risk.")
        return 0

    info = mt5.symbol_info(symbol)
    if info is None: return 0

    tick_size = info.trade_tick_size
    tick_value = info.trade_tick_value

    if tick_size == 0 or tick_value == 0:
        return 0

    ticks_at_risk = abs(entry_price - sl_price) / tick_size
    risk_for_one_lot = ticks_at_risk * tick_value

    if risk_for_one_lot == 0:
        return 0

    # حساب المبلغ المراد المخاطرة به (5% من الرصيد)
    risk_amount = balance * RISK_PERCENT
    calculated_lot = risk_amount / risk_for_one_lot

    min_lot = info.volume_min
    max_lot = info.volume_max
    step = info.volume_step

    if step == 0: step = 0.01

    calculated_lot = round(calculated_lot / step) * step

    # 🛑 شرط المخاطرة الصارم: إذا كان أصغر لوت سيخسرك أكثر من 5%، نرفض الصفقة
    if calculated_lot < min_lot:
        print(f"⚠️ Risk exceeds {RISK_PERCENT*100}% of balance even with min lot {min_lot}! Trade rejected.")
        return 0

    if calculated_lot > max_lot: return max_lot

    return round(calculated_lot, 2)

# ============================================================
# جلب صفقات المستثمر الحقيقية (المفتوحة فقط)
# ============================================================
def get_investor_data():
    if not mt5.initialize(path=INVESTOR_TERMINAL_PATH):
        print("❌ Failed to connect Investor Terminal")
        return None

    positions = mt5.positions_get()
    mt5.shutdown()

    return {p.ticket: p for p in positions} if positions else {}

# ============================================================
# مزامنة جميع الصفقات على الحقيقي
# ============================================================
def sync_all_data(inv_pos_dict, current_time):
    if not mt5.initialize(path=REAL_ACCOUNT_TERMINAL_PATH):
        print(f"[{current_time}] ❌ Failed to connect Real Terminal")
        return

    account_info = mt5.account_info()
    if not account_info:
        mt5.shutdown()
        return
        
    real_balance = account_info.balance
    
    real_positions = mt5.positions_get()
    real_pos_dict = {p.ticket: p for p in real_positions} if real_positions else {}

    # 1. إغلاق الصفقات المنتهية
    for inv_id in list(pos_map.keys()):
        if inv_id not in inv_pos_dict:
            real_id = pos_map[inv_id]
            if real_id in real_pos_dict:
                pos = real_pos_dict[real_id]
                close_type = mt5.ORDER_TYPE_BUY if pos.type == mt5.ORDER_TYPE_SELL else mt5.ORDER_TYPE_SELL
                tick = mt5.symbol_info_tick(pos.symbol)
                price = tick.ask if close_type == mt5.ORDER_TYPE_BUY else tick.bid
                
                req = {
                    "action": mt5.TRADE_ACTION_DEAL,
                    "symbol": pos.symbol,
                    "volume": pos.volume,
                    "type": close_type,
                    "position": real_id,
                    "price": price,
                    "deviation": SLIPPAGE,
                    "magic": MAGIC_NUMBER,
                    "type_time": mt5.ORDER_TIME_GTC,
                    "type_filling": FILLING_TYPE,
                }
                res = mt5.order_send(req)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    print(f"[{current_time}] 🔒 Closed Position {pos.symbol}")
            del pos_map[inv_id]

    # 2. فتح الصفقات المباشرة الجديدة
    for inv_id, inv_pos in inv_pos_dict.items():
        if inv_id not in pos_map:
            real_symbol = get_cleaned_symbol(inv_pos.symbol)

            mt5.symbol_select(real_symbol, True)
            tick = mt5.symbol_info_tick(real_symbol)
            
            if not tick: 
                print(f"[{current_time}] ⚠️ Cannot find price for '{real_symbol}'! Ensure it's in Market Watch.")
                continue
            
            curr_price = tick.ask if inv_pos.type == 0 else tick.bid
            
            # فلتر: إذا كان السعر 0.0 (السوق مغلق أو الاتصال ضعيف)
            if curr_price == 0.0:
                print(f"[{current_time}] ⚠️ Current price for {real_symbol} is 0.0! Waiting for valid tick.")
                continue
            
            # فلتر حماية السعر (الانزلاق)
            max_diff, _ = get_dynamic_thresholds(real_symbol)
            diff = calculate_pip_difference(real_symbol, inv_pos.price_open, curr_price)
            if diff > max_diff:
                print(f"[{current_time}] ⛔ Skipped {real_symbol} | Price moved by {diff:.1f} pips (> {max_diff})")
                print(f"   ➔ Investor Open Price: {inv_pos.price_open} | Real Current Price: {curr_price}")
                continue
            
            # حساب اللوت مع فحص المخاطرة (5%)
            trade_lot = calculate_lot_size(real_symbol, curr_price, inv_pos.sl, real_balance)
            
            # إذا رجعت الدالة 0، فهذا يعني أن الصفقة مرفوضة بسبب المخاطرة
            if trade_lot == 0:
                print(f"[{current_time}] ⛔ Skipped {real_symbol} | Risk conditions not met (Exceeds 5% or No SL).")
                continue
            
            req = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": real_symbol,
                "volume": trade_lot,
                "type": inv_pos.type,
                "price": curr_price,
                "sl": float(inv_pos.sl),
                "tp": float(inv_pos.tp),
                "magic": MAGIC_NUMBER,
                "deviation": SLIPPAGE,
                "comment": f"Market {inv_pos.ticket}",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": FILLING_TYPE,
            }
            res = mt5.order_send(req)
            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                pos_map[inv_id] = res.order
                print(f"[{current_time}] ✅ Copied Market Trade {real_symbol} | Lot {trade_lot}")
                
                class Dummy: pass
                d = Dummy()
                d.symbol, d.type, d.price_open = real_symbol, inv_pos.type, curr_price
                real_pos_dict[res.order] = d
            else:
                comment = res.comment if res else "Unknown Error"
                print(f"[{current_time}] ❌ Failed to copy {real_symbol}: {comment}")

    mt5.shutdown()

# ============================================================
# التشغيل الرئيسي مع التتبع المستمر (Logs)
# ============================================================
print("🚀 Solid Copy System Active... Syncing ONLY real Executed Trades.\n")

try:
    while True:
        current_time = datetime.now().strftime("%H:%M:%S")
        print(f"[{current_time}] 🔄 Checking for new trades...")
        
        inv_positions = get_investor_data()
        
        if inv_positions is not None:
            print(f"[{current_time}] 📊 Found {len(inv_positions)} active position(s) in Investor Account.")
            sync_all_data(inv_positions, current_time)
        else:
            print(f"[{current_time}] ⚠️ Could not read Investor Account (Check terminal connection).")
            
        print(f"[{current_time}] 💤 Waiting 5 seconds...\n")
        print("-" * 40) 
        
        time.sleep(5)

except KeyboardInterrupt:
    print("\n🛑 Stopped by user.")