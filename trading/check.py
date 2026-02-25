import MetaTrader5 as mt5

path = r"D:\mt5\zaid Ramdan mt5\terminal64.exe"
login = 960750
password = "vvwvVS3c3%R*"
server = "MaxifyFx-live"
symbol = "XAUUSD#"

print("Connecting to Broker...")
if not mt5.initialize(path=path, login=login, password=password, server=server):
    print("Failed to connect to the MT5 terminal")
    quit()

account_info = mt5.account_info()
if account_info is not None:
    print("\n=== Account Permissions Check ===")
    print(f"- Manual Trading Allowed: {account_info.trade_allowed}")
    print(f"- Automated Trading (EA/Bots) Allowed by Server: {account_info.trade_expert}")

sym_info = mt5.symbol_info(symbol)
if sym_info is not None:
    print("\n=== Symbol Permissions Check (XAUUSD.) ===")
    modes = {
        0: "Disabled", 
        1: "Long Only", 
        2: "Short Only", 
        3: "Close Only", 
        4: "Full Access"
    }
    trade_mode = sym_info.trade_mode
    print(f"- Trade Mode for this symbol: {modes.get(trade_mode, trade_mode)}")

mt5.shutdown()