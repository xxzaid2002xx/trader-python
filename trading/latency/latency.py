import socket
import ssl
import time
import re
from datetime import datetime
from multiprocessing import Process, Queue
import MetaTrader5 as mt5

# =====================================
# اعدادات مزود السعر السريع (cTrader FIX API)
# =====================================
FIX_CONFIG = {
    "host": "demo-uk-eqx-01.p.c-trader.com",
    "port": 5211,
    "sender_comp_id": "demo.icmarkets.9835550",
    "target_comp_id": "cServer",
    "sender_sub_id": "QUOTE",
    "account": "9835550",
    "password": "XXzaid@2002XX", 
    "name": "FIX_FAST"
}
# =====================================
# اعدادات الوسيط البطيء (MT5 - JustMarkets)
# =====================================
XM_CONFIG = {
    "path": r"D:\mt5 broker 2\terminal64.exe",
    "login": 6458477,
    "password": "zG%2a*Ba3b%3",
    "server": "Oxshare-Server",
    "name": "MT5_SLOW"
}

SYMBOL_MT5 = "XAUUSD."
SYMBOL_FIX = "41" 

# =====================================
# دوال مساعدة لبروتوكول FIX
# =====================================
def create_fix_message(msg_type, seq_num, body_str, config):
    time_str = datetime.utcnow().strftime('%Y%m%d-%H:%M:%S.000')
    header = f"35={msg_type}|49={config['sender_comp_id']}|50={config['sender_sub_id']}|56={config['target_comp_id']}|57={config['sender_sub_id']}|34={seq_num}|52={time_str}|"
    message_data = header + body_str
    body_length = len(message_data)
    full_msg = f"8=FIX.4.4|9={body_length}|{message_data}"
    full_msg_soh = full_msg.replace('|', '\x01')
    checksum = sum(ord(c) for c in full_msg_soh) % 256
    final_msg = full_msg_soh + f"10={checksum:03d}\x01"
    return final_msg

# =====================================
# عملية السعر السريع (FIX API Process)
# =====================================
def fix_process(config, q):
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    try:
        sock = socket.create_connection((config['host'], config['port']))
        ssock = context.wrap_socket(sock, server_hostname=config['host'])
        print(f"Connected -> {config['name']} (London LD4)")

        logon_body = f"98=0|108=30|141=Y|553={config['account']}|554={config['password']}|"
        logon_msg = create_fix_message('A', 1, logon_body, config)
        ssock.send(logon_msg.encode('ascii'))
        
        logon_resp = ssock.recv(4096).decode('ascii')
        print(f"Logon Response: {logon_resp.replace(chr(1), '|')}")

        md_body = f"262=REQ_1|263=1|264=1|265=1|267=2|269=0|269=1|146=1|55={SYMBOL_FIX}|"
        md_msg = create_fix_message('V', 2, md_body, config)
        ssock.send(md_msg.encode('ascii'))

        while True:
            data = ssock.recv(4096).decode('ascii')
            if not data:
                print("FIX Server closed the connection!")
                break
            
            clean_data = data.replace('\x01', '|')
            
            if '35=0' not in clean_data and '35=1' not in clean_data and '35=W' not in clean_data:
                pass 
            
            if '35=0' in clean_data or '35=1' in clean_data:
                hb_msg = create_fix_message('0', 3, "", config)
                ssock.send(hb_msg.encode('ascii'))
                continue

            if '35=W' in clean_data or '35=X' in clean_data:
                prices = re.findall(r'270=([\d\.]+)', clean_data)
                if len(prices) >= 2:
                    bid = float(prices[0])
                    ask = float(prices[1])
                    t_msc = int(time.time() * 1000)
                    q.put((config["name"], t_msc, bid, ask))

    except Exception as e:
        print(f"Failed to connect {config['name']}: {e}")

# =====================================
# عملية الوسيط البطيء (MT5 Process)
# =====================================
def broker_process(config, q):
    if not mt5.initialize(
        path=config["path"],
        login=config["login"],
        password=config["password"],
        server=config["server"]
    ):
        print(f"Failed to connect {config['name']}")
        return

    print(f"Connected -> {config['name']}")

    symbol_info = mt5.symbol_info(SYMBOL_MT5)
    if symbol_info is None:
        print(f"{config['name']} Symbol not found")
        return

    if not symbol_info.visible:
        mt5.symbol_select(SYMBOL_MT5, True)

    while True:
        tick = mt5.symbol_info_tick(SYMBOL_MT5)
        if tick:
            q.put((
                config["name"],
                tick.time_msc,
                tick.bid,
                tick.ask
            ))
        
        time.sleep(0.001)

# =====================================
# دالة تنفيذ الصفقات على MT5
# =====================================
def execute_trade(order_type, symbol, target_distance, lot_size=0.01):
    tick = mt5.symbol_info_tick(symbol)
    symbol_info = mt5.symbol_info(symbol)
    if not tick or not symbol_info: 
        return False
    
    # تحديد نوع الملء المدعوم ديناميكياً
    filling_type = mt5.ORDER_FILLING_FOK
    if symbol_info.filling_mode & 1:
        filling_type = mt5.ORDER_FILLING_FOK
    elif symbol_info.filling_mode & 2:
        filling_type = mt5.ORDER_FILLING_IOC
    else:
        filling_type = mt5.ORDER_FILLING_RETURN

    # إعداد الأسعار وتحديد نوع الصفقة
    if order_type == mt5.ORDER_TYPE_BUY:
        price = tick.ask
        sl = price - target_distance
        tp = price + target_distance
        action_name = "BUY"
    else:
        price = tick.bid
        sl = price + target_distance
        tp = price - target_distance
        action_name = "SELL"
        
    # بناء الطلب
    request = {
        "action": mt5.TRADE_ACTION_DEAL,
        "symbol": symbol,
        "volume": float(lot_size),
        "type": order_type,
        "price": price,
        "sl": sl,
        "tp": tp,
        "deviation": 20,
        "magic": 998877,
        "comment": "Arb_Bot",
        "type_time": mt5.ORDER_TIME_GTC,
        "type_filling": filling_type,
    }
    
    # إرسال الطلب
    result = mt5.order_send(request)
    if result.retcode != mt5.TRADE_RETCODE_DONE:
        print(f"\n❌ Failed to send {action_name} order. Error: {result.retcode} - {result.comment}")
        return False # إرجاع خطأ لكي يعلم البوت أن الصفقة لم تُفتح
    else:
        print(f"\n✅ {action_name} Order Opened Successfully! Price: {price} | TP: {tp:.2f} | SL: {sl:.2f}")
        return True # إرجاع نجاح لكي نوقف فتح صفقات أخرى مؤقتاً


# =====================================
# الدالة الرئيسية للبرنامج (MAIN)
# =====================================
if __name__ == "__main__":
    q = Queue()

    p_fast = Process(target=fix_process, args=(FIX_CONFIG, q))
    p_slow = Process(target=broker_process, args=(XM_CONFIG, q))

    p_fast.start()
    p_slow.start()

    # تهيئة MT5 في العملية الرئيسية لتتمكن من إرسال الأوامر
    if not mt5.initialize(path=XM_CONFIG["path"], login=XM_CONFIG["login"], password=XM_CONFIG["password"], server=XM_CONFIG["server"]):
        print("Main process failed to initialize MT5 for trading.")

    latest = {
        "FIX_FAST": {"time": None, "bid": None, "ask": None},
        "MT5_SLOW": {"time": None, "bid": None, "ask": None}
    }

    print("Price Difference Monitor & Auto Trader Started...\n")

    SPREAD_VALUE = 0.15 
    LOT_SIZE = 0.01 

    try:
        while True:
            while not q.empty():
                name, t_msc, bid, ask = q.get()
                latest[name] = {
                    "time": t_msc,
                    "bid": bid,
                    "ask": ask
                }

            if latest["FIX_FAST"]["bid"] is not None and latest["MT5_SLOW"]["bid"] is not None:
                price_diff = latest["FIX_FAST"]["bid"] - latest["MT5_SLOW"]["bid"]
                abs_diff = abs(price_diff)

                if price_diff > 0:
                    leader = "FIX is Higher"
                elif price_diff < 0:
                    leader = "MT5 is Higher"
                else:
                    leader = "Same Price"

                # ---------------------------------------------------------
                # منطق التداول: إذا كان الفارق 2 أو أكثر
                # ---------------------------------------------------------
                if abs_diff >= 2.0:
                    # التحقق من الصفقات المفتوحة بدقة
                    open_positions = mt5.positions_get(symbol=SYMBOL_MT5)
                    
                    if open_positions is None or len(open_positions) == 0:
                        target_distance = abs_diff - SPREAD_VALUE
                        
                        if target_distance > 0:
                            trade_success = False # متغير للتأكد من نجاح العملية
                            
                            if price_diff >= 2.0:
                                print(f"\n🚀 Signal Triggered! Diff = {price_diff:.2f}. Executing BUY...")
                                trade_success = execute_trade(mt5.ORDER_TYPE_BUY, SYMBOL_MT5, target_distance, LOT_SIZE)
                                
                            elif price_diff <= -2.0:
                                print(f"\n🚀 Signal Triggered! Diff = {price_diff:.2f}. Executing SELL...")
                                trade_success = execute_trade(mt5.ORDER_TYPE_SELL, SYMBOL_MT5, target_distance, LOT_SIZE)

                            # إذا تم فتح الصفقة بنجاح، نوقف البوت لثانية واحدة
                            # حتى يتمكن سيرفر المنصة من تسجيل الصفقة ولا يفتح صفقة مزدوجة
                            if trade_success:
                                print("⏳ Waiting for broker to register position...")
                                time.sleep(1) 


                now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(
                    f"{now} | "
                    f"FIX: {latest['FIX_FAST']['bid']} | "
                    f"MT5: {latest['MT5_SLOW']['bid']} | "
                    f"Diff: {price_diff:.2f} | "
                    f"{leader}", end='\r'
                )

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\nStopping Processes...")
        p_fast.terminate()
        p_slow.terminate()
        mt5.shutdown()