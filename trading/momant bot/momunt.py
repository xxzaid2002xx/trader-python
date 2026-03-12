import MetaTrader5 as mt5
import pandas as pd

# مسار برنامج MT5 الذي طلبته
MT5_PATH = r"D:\mt5\MASTER\terminal64.exe"

SYMBOL = "XAUUSD!"               # الزوج الذي نريد التداول عليه
LOT_SIZE = 0.01                  # حجم الصفقة
MAGIC_NUMBER = 999999            # رقم مميز ليتعرف البوت على صفقاته

def connect_to_mt5():
    """تهيئة الاتصال بمنصة MT5 باستخدام المسار فقط للاتصال بالنسخة المفتوحة مسبقاً"""
    print("Connecting to the already open MT5...")
    
    # تهيئة المنصة باستخدام المسار فقط بدون بيانات تسجيل دخول
    initialized = mt5.initialize(path=MT5_PATH)
    
    if initialized:
        print("Successfully connected to MT5.")
        return True
    else:
        print(f"Connection failed. Error code: {mt5.last_error()}")
        return False

def check_momentum_and_trade():
    """دالة تقرأ السعر، تحسب الزخم البسيط، وتنفذ صفقة"""
    
    # التأكد من أن الزوج متاح في نافذة مراقبة السوق
    mt5.symbol_select(SYMBOL, True)
    
    # جلب آخر 10 شمعات على فريم الساعة لحساب الزخم
    rates = mt5.copy_rates_from_pos(SYMBOL, mt5.TIMEFRAME_H1, 0, 10)
    if rates is None:
        print("Failed to fetch prices.")
        return
        
    # تحويل البيانات إلى Pandas DataFrame
    df = pd.DataFrame(rates)
    
    # حساب الزخم البسيط
    current_close = df.iloc[-1]['close']
    old_close = df.iloc[0]['close']
    momentum = current_close - old_close
    
    print(f"Current price for {SYMBOL}: {current_close} | Momentum: {momentum:.5f}")
    
    # منطق التداول (تم تعديل الرقم ليتناسب مع حركة الذهب)
    # 2.0 تعني أن السعر تحرك بمقدار دولارين
    if momentum > 2.0: 
        print("Buy signal! Executing Buy order...")
        send_order(mt5.ORDER_TYPE_BUY)
        
    elif momentum < -2.0: 
        print("Sell signal! Executing Sell order...")
        send_order(mt5.ORDER_TYPE_SELL)
    else:
        print("No strong signal currently. Waiting...")

def send_order(order_type):
    """إرسال أمر التداول لمنصة MT5"""
    
    tick = mt5.symbol_info_tick(SYMBOL)
    if tick is None:
        print("Failed to get tick info.")
        return
        
    price = tick.ask if order_type == mt5.ORDER_TYPE_BUY else tick.bid
    
    # إعداد تفاصيل الطلب
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": SYMBOL,
        "volume": LOT_SIZE,
        "type": order_type,
        "price": price,
        "deviation": 20, 
        "magic": MAGIC_NUMBER,
        "comment": "Momentum Bot Python",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": mt5.ORDER_FILLING_IOC,
    }
    
    # إرسال الطلب
    result = mt5.order_send(request)
    
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"Order send failed! Error code: {result.retcode}")
        # طباعة تفاصيل الطلب لمعرفة سبب الرفض إن وجد
        print(f"Request data: {request}")
    else:
        print(f"Trade opened successfully! Ticket number: {result.order}")

# تشغيل البوت
if __name__ == "__main__":
    if connect_to_mt5():
        print("Bot is running now... Checking the market once.")
        check_momentum_and_trade()
        
        # إغلاق الاتصال بعد الانتهاء لتحرير الذاكرة
        mt5.shutdown()
        print("Connection closed. Task finished.")