import os
import time
import threading
import requests
import base64

from flask import Flask

from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# =========================
# CONFIG
# =========================

RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

WSOL = "So11111111111111111111111111111111111111112"

CONFIG = {

    # valor por trade
    "trade_amount_sol": 0.02,

    # filtros agressivos
    "min_liquidity_usd": 200,
    "min_volume_usd": 40,

    # venda
    "take_profit": 1.50,
    "stop_loss": 0.70,

    # tempo máximo segurando
    "max_hold_minutes": 10,

    # intervalo scanner
    "scan_interval": 5,

    # limite de trades simultâneos
    "max_active_trades": 3,

    # slippage
    "slippage_bps": 1800,

    "priority_fee": 1500000
}

# =========================
# INIT
# =========================

solana_client = Client(RPC_URL)

wallet = Keypair.from_base58_string(PRIVATE_KEY)

active_trades = []
blacklist = set()

buy_lock = False

HEADERS = {"User-Agent": "Mozilla/5.0"}

# =========================
# SAFE REQUEST
# =========================

def safe_get(url):

    try:

        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code != 200:
            return None

        return r.json()

    except:
        return None


# =========================
# PRICE
# =========================

def get_price(token):

    url = f"https://api.dexscreener.com/latest/dex/tokens/{token}"

    data = safe_get(url)

    if not data:
        return None

    pairs = data.get("pairs", [])

    if not pairs:
        return None

    return float(pairs[0]["priceUsd"])


# =========================
# JUPITER SWAP
# =========================

def swap(input_mint, output_mint, amount):

    try:

        lamports = int(amount * 1e9)

        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={lamports}&slippageBps={CONFIG['slippage_bps']}"

        quote = safe_get(quote_url)

        if not quote:
            return False, None

        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(wallet.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }

        swap_tx = requests.post(
            "https://quote-api.jup.ag/v6/swap",
            json=payload
        ).json()

        tx = VersionedTransaction.from_bytes(
            base64.b64decode(swap_tx["swapTransaction"])
        )

        signed = VersionedTransaction(tx.message, [wallet])

        sig = solana_client.send_raw_transaction(bytes(signed))

        return True, str(sig.value)

    except Exception as e:

        print("swap error", e)

        return False, None


# =========================
# VALID PAIR
# =========================

def valid_pair(pair):

    try:

        token = pair["baseToken"]["address"]
        symbol = pair["baseToken"]["symbol"]

        if token == WSOL:
            return False

        if token in blacklist:
            return False

        liquidity = float(pair.get("liquidity", {}).get("usd", 0))
        volume = float(pair.get("volume", {}).get("h24", 0))
        price = float(pair.get("priceUsd", 0))

        if liquidity < CONFIG["min_liquidity_usd"]:
            return False

        if volume < CONFIG["min_volume_usd"]:
            return False

        if price <= 0:
            return False

        return True

    except:
        return False


# =========================
# BUY
# =========================

def buy(pair):

    global buy_lock

    if buy_lock:
        return

    if len(active_trades) >= CONFIG["max_active_trades"]:
        return

    token = pair["baseToken"]["address"]
    symbol = pair["baseToken"]["symbol"]

    buy_lock = True

    print("🚀 BUY", symbol)

    ok, tx = swap(WSOL, token, CONFIG["trade_amount_sol"])

    if not ok:
        buy_lock = False
        return

    price = float(pair["priceUsd"])

    trade = {
        "token": token,
        "symbol": symbol,
        "buy_price": price,
        "time": time.time()
    }

    active_trades.append(trade)

    blacklist.add(token)

    threading.Thread(
        target=monitor_trade,
        args=(trade,),
        daemon=True
    ).start()

    time.sleep(2)

    buy_lock = False


# =========================
# SELL
# =========================

def sell(trade):

    token = trade["token"]
    symbol = trade["symbol"]

    print("💰 SELL", symbol)

    swap(token, WSOL, CONFIG["trade_amount_sol"])

    if trade in active_trades:
        active_trades.remove(trade)


# =========================
# MONITOR TRADE
# =========================

def monitor_trade(trade):

    start = time.time()

    while True:

        price = get_price(trade["token"])

        if not price:
            time.sleep(4)
            continue

        if price >= trade["buy_price"] * CONFIG["take_profit"]:
            sell(trade)
            return

        if price <= trade["buy_price"] * CONFIG["stop_loss"]:
            sell(trade)
            return

        if time.time() - start > CONFIG["max_hold_minutes"] * 60:
            sell(trade)
            return

        time.sleep(4)


# =========================
# SCANNER
# =========================

def scan():

    while True:

        try:

            print("🔎 scanning...")

            url = "https://api.dexscreener.com/latest/dex/search?q=SOL"

            data = safe_get(url)

            if not data:
                time.sleep(5)
                continue

            pairs = data.get("pairs", [])

            for pair in pairs[:50]:

                if valid_pair(pair):

                    buy(pair)

        except Exception as e:

            print("scan error", e)

        time.sleep(CONFIG["scan_interval"])


# =========================
# SERVER (KEEP ALIVE)
# =========================

app = Flask(__name__)

@app.route("/")
def home():
    return "bot running"


def run_server():
    app.run(host="0.0.0.0", port=10000)


# =========================
# START
# =========================

if __name__ == "__main__":

    print("🚀 MEMECOIN BOT STARTED")

    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=scan, daemon=True).start()

    while True:
        time.sleep(60)
