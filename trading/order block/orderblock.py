import MetaTrader5 as mt5
from datetime import datetime

# Path to MT5 terminal
mt5_path = r"C:\Program Files\MetaTrader 5\terminal64.exe"

# Initialize connection using specific terminal path
if not mt5.initialize(path=mt5_path):
    print("Failed to connect to MetaTrader 5 at specified path")
    quit()

print("Connected to MetaTrader 5 successfully")

# Get all pending orders
orders = mt5.orders_get()

if orders is None or len(orders) == 0:
    print("No pending orders found")
else:
    print(f"Total pending orders: {len(orders)}\n")

    for order in orders:
        order_type_dict = {
            mt5.ORDER_TYPE_BUY_LIMIT: "BUY LIMIT",
            mt5.ORDER_TYPE_SELL_LIMIT: "SELL LIMIT",
            mt5.ORDER_TYPE_BUY_STOP: "BUY STOP",
            mt5.ORDER_TYPE_SELL_STOP: "SELL STOP",
            mt5.ORDER_TYPE_BUY_STOP_LIMIT: "BUY STOP LIMIT",
            mt5.ORDER_TYPE_SELL_STOP_LIMIT: "SELL STOP LIMIT",
        }

        order_type = order_type_dict.get(order.type, "UNKNOWN")

        print("---------------")
        print(f"Ticket: {order.ticket}")
        print(f"Symbol: {order.symbol}")
        print(f"Type: {order_type}")
        print(f"Price: {order.price_open}")
        print(f"Take Profit: {order.tp}")
        print(f"Stop Loss: {order.sl}")
        print(f"Volume: {order.volume_current}")
        print(f"Setup Time: {datetime.fromtimestamp(order.time_setup)}")

mt5.shutdown()