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
    "password": "XXzaid@2002XX", # تم تحديث كلمة المرور هنا
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
SYMBOL_FIX = "41" # رمز الذهب في سي تريدر، قد يحتاج لتعديل لاحقا

# =====================================
# دوال مساعدة لبروتوكول FIX
# =====================================
def create_fix_message(msg_type, seq_num, body_str, config):
    time_str = datetime.utcnow().strftime('%Y%m%d-%H:%M:%S.000')
    
    # التعديل هنا: تمت اضافة التاج 57 الخاص بـ TargetSubID
    header = f"35={msg_type}|49={config['sender_comp_id']}|50={config['sender_sub_id']}|56={config['target_comp_id']}|57={config['sender_sub_id']}|34={seq_num}|52={time_str}|"
    
    message_data = header + body_str
    body_length = len(message_data)
    
    full_msg = f"8=FIX.4.4|9={body_length}|{message_data}"
    full_msg_soh = full_msg.replace('|', '\x01')
    
    checksum = sum(ord(c) for c in full_msg_soh) % 256
    final_msg = full_msg_soh + f"10={checksum:03d}\x01"
    
    return final_msg

# =====================================
# عملية السعر السريع (FIX API Process) - نسخة كشف الاخطاء
# =====================================
def fix_process(config, q):
    context = ssl.create_default_context()
    context.check_hostname = False
    context.verify_mode = ssl.CERT_NONE

    try:
        sock = socket.create_connection((config['host'], config['port']))
        ssock = context.wrap_socket(sock, server_hostname=config['host'])
        print(f"Connected -> {config['name']} (London LD4)")

        # ارسال طلب تسجيل الدخول
        logon_body = f"98=0|108=30|141=Y|553={config['account']}|554={config['password']}|"
        logon_msg = create_fix_message('A', 1, logon_body, config)
        ssock.send(logon_msg.encode('ascii'))
        
        # استلام وطباعة رد تسجيل الدخول لمعرفة حالة القبول او الرفض
        logon_resp = ssock.recv(4096).decode('ascii')
        print(f"Logon Response: {logon_resp.replace(chr(1), '|')}")

        # ارسال طلب الاشتراك باسعار الذهب
        md_body = f"262=REQ_1|263=1|264=1|265=1|267=2|269=0|269=1|146=1|55={SYMBOL_FIX}|"
        md_msg = create_fix_message('V', 2, md_body, config)
        ssock.send(md_msg.encode('ascii'))

        # حلقة الاستماع المستمرة
        while True:
            data = ssock.recv(4096).decode('ascii')
            if not data:
                print("FIX Server closed the connection!")
                break
            
            clean_data = data.replace('\x01', '|')
            
            # طباعة اي رسالة تصل من الخادم (عدا نبض القلب او الاسعار) للاستكشاف
            if '35=0' not in clean_data and '35=1' not in clean_data and '35=W' not in clean_data:
                print(f"Server Message: {clean_data}")
            
            # الرد على نبضات الخادم للحفاظ على الاتصال
            if '35=0' in clean_data or '35=1' in clean_data:
                hb_msg = create_fix_message('0', 3, "", config)
                ssock.send(hb_msg.encode('ascii'))
                continue

            # استخراج السعر من رسائل السوق
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
        
        # التاخير شبه معدوم للحفاظ على سرعة المعالجة
        time.sleep(0.001)

# =====================================
# الدالة الرئيسية للبرنامج (MAIN)
# =====================================
if __name__ == "__main__":
    q = Queue()

    p_fast = Process(target=fix_process, args=(FIX_CONFIG, q))
    p_slow = Process(target=broker_process, args=(XM_CONFIG, q))

    p_fast.start()
    p_slow.start()

    latest = {
        "FIX_FAST": {"time": None, "bid": None, "ask": None},
        "MT5_SLOW": {"time": None, "bid": None, "ask": None}
    }

    print("Price Difference Monitor Started...\n")

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

                if price_diff > 0:
                    leader = "FIX is Higher (Buy Signal)"
                elif price_diff < 0:
                    leader = "MT5 is Higher (Sell Signal)"
                else:
                    leader = "Same Price"

                now = datetime.now().strftime("%H:%M:%S.%f")[:-3]
                print(
                    f"{now} | "
                    f"FIX: {latest['FIX_FAST']['bid']} | "
                    f"MT5: {latest['MT5_SLOW']['bid']} | "
                    f"Diff: {price_diff:.2f} | "
                    f"{leader}"
                )

            time.sleep(0.001)

    except KeyboardInterrupt:
        print("\nStopping Processes...")
        p_fast.terminate()
        p_slow.terminate()
        mt5.shutdown()