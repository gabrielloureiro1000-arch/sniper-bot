import os
import time
import threading
import requests
import base64
import telebot

from flask import Flask

from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction


# ================= CONFIG =================

RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("PRIVATE_KEY")

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

WSOL = "So11111111111111111111111111111111111111112"

CONFIG = {

    "trade_amount_sol": 0.02,

    "min_liquidity_usd": 300,
    "min_volume_usd": 100,

    "take_profit": 1.6,
    "stop_loss": 0.7,

    "max_hold_minutes": 20,

    "scan_interval": 5,

    "max_active_trades": 3,

    "slippage_bps": 2000,

    "priority_fee": 1500000
}


# ================= INIT =================

bot = telebot.TeleBot(TELEGRAM_TOKEN)

solana_client = Client(RPC_URL)

wallet = Keypair.from_base58_string(PRIVATE_KEY)

active_trades = []

blacklist = set()

stats = {
    "trades": 0,
    "wins": 0,
    "losses": 0
}

HEADERS = {"User-Agent": "Mozilla/5.0"}


# ================= TELEGRAM =================

def send(msg):

    try:
        bot.send_message(CHAT_ID, msg)
    except:
        pass


# ================= REQUEST =================

def safe_get(url):

    try:

        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code != 200:
            return None

        return r.json()

    except:
        return None


# ================= PRICE =================

def get_price(token):

    url = f"https://api.dexscreener.com/latest/dex/tokens/{token}"

    data = safe_get(url)

    if not data:
        return None

    pairs = data.get("pairs", [])

    if not pairs:
        return None

    return float(pairs[0]["priceUsd"])


# ================= SWAP =================

def swap(input_mint, output_mint, amount):

    try:

        lamports = int(amount * 1e9)

        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={lamports}&slippageBps={CONFIG['slippage_bps']}"

        quote = safe_get(quote_url)

        if not quote:
            return False

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

        solana_client.send_raw_transaction(bytes(signed))

        return True

    except Exception as e:

        print("swap error", e)

        return False


# ================= FILTER =================

def valid_pair(pair):

    try:

        token = pair["baseToken"]["address"]

        if token == WSOL:
            return False

        if token in blacklist:
            return False

        liquidity = float(pair["liquidity"]["usd"])
        volume = float(pair["volume"]["h24"])

        if liquidity < CONFIG["min_liquidity_usd"]:
            return False

        if volume < CONFIG["min_volume_usd"]:
            return False

        return True

    except:
        return False


# ================= BUY =================

def buy(pair):

    if len(active_trades) >= CONFIG["max_active_trades"]:
        return

    token = pair["baseToken"]["address"]
    symbol = pair["baseToken"]["symbol"]

    print("🚀 BUY", symbol)

    ok = swap(WSOL, token, CONFIG["trade_amount_sol"])

    if not ok:
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

    stats["trades"] += 1

    send(
f"""🚀 COMPRA

Token: {symbol}
Preço: ${price}
Liquidez: ${pair["liquidity"]["usd"]}
"""
)

    threading.Thread(
        target=monitor,
        args=(trade,),
        daemon=True
    ).start()


# ================= SELL =================

def sell(trade):

    token = trade["token"]
    symbol = trade["symbol"]

    price = get_price(token)

    swap(token, WSOL, CONFIG["trade_amount_sol"])

    pnl = price / trade["buy_price"]

    if pnl >= 1:
        stats["wins"] += 1
    else:
        stats["losses"] += 1

    send(
f"""💰 VENDA

Token: {symbol}

Resultado: {round((pnl-1)*100,2)}%
"""
)

    active_trades.remove(trade)


# ================= MONITOR =================

def monitor(trade):

    start = time.time()

    while True:

        price = get_price(trade["token"])

        if not price:
            time.sleep(5)
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

        time.sleep(5)


# ================= REPORT =================

def report():

    while True:

        time.sleep(7200)

        send(
f"""📊 RELATÓRIO BOT

Trades: {stats["trades"]}
Wins: {stats["wins"]}
Losses: {stats["losses"]}

Trades ativos: {len(active_trades)}
"""
)


# ================= SCAN =================

def scan():

    while True:

        try:

            print("🔎 scanning...")

            url = "https://api.dexscreener.com/latest/dex/search?q=SOL"

            data = safe_get(url)

            if not data:
                time.sleep(5)
                continue

            pairs = data["pairs"]

            for pair in pairs[:60]:

                if valid_pair(pair):

                    buy(pair)

        except Exception as e:

            print("scan error", e)

        time.sleep(CONFIG["scan_interval"])


# ================= SERVER =================

app = Flask(__name__)

@app.route("/")
def home():
    return "bot running"


# ================= START =================

if __name__ == "__main__":

    send("🤖 BOT MEMECOIN INICIADO")

    threading.Thread(target=scan).start()
    threading.Thread(target=report).start()

    app.run(host="0.0.0.0", port=10000)
