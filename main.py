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


# ================= ENV =================

RPC_URL = os.environ.get("RPC_URL")
PRIVATE_KEY = os.environ.get("WALLET_PRIVATE_KEY")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = os.environ.get("CHAT_ID")

if not RPC_URL or not PRIVATE_KEY:
    raise Exception("Variáveis de ambiente faltando")


# ================= INIT =================

bot = telebot.TeleBot(TELEGRAM_TOKEN)

client = Client(RPC_URL)

wallet = Keypair.from_base58_string(PRIVATE_KEY)

WSOL = "So11111111111111111111111111111111111111112"


# ================= CONFIG =================

CONFIG = {

    "BUY_AMOUNT": 0.02,

    "MIN_LIQUIDITY": 1000,
    "MIN_VOLUME": 500,

    "TAKE_PROFIT": 1.8,
    "STOP_LOSS": 0.65,

    "SCAN_INTERVAL": 6,

    "MAX_TRADES": 3
}


active_trades = []
seen_tokens = set()
blacklist = set()


stats = {

    "trades": 0,
    "wins": 0,
    "losses": 0
}


# ================= TELEGRAM =================

def send(msg):

    try:
        bot.send_message(CHAT_ID, msg)
    except:
        pass


# ================= HTTP =================

def safe_get(url):

    try:

        r = requests.get(url, timeout=10)

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

def swap(input_mint, output_mint, sol_amount):

    try:

        lamports = int(sol_amount * 1e9)

        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={lamports}&slippageBps=2000"

        quote = safe_get(quote_url)

        if not quote:
            return False

        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(wallet.pubkey())
        }

        swap_tx = requests.post(
            "https://quote-api.jup.ag/v6/swap",
            json=payload
        ).json()

        tx = VersionedTransaction.from_bytes(
            base64.b64decode(swap_tx["swapTransaction"])
        )

        signed = VersionedTransaction(tx.message, [wallet])

        client.send_raw_transaction(bytes(signed))

        return True

    except Exception as e:

        print("swap error:", e)

        return False


# ================= BUY =================

def buy(pair):

    token = pair["baseToken"]["address"]
    symbol = pair["baseToken"]["symbol"]

    if token == WSOL:
        return

    if token in blacklist:
        return

    if token in seen_tokens:
        return

    if len(active_trades) >= CONFIG["MAX_TRADES"]:
        return

    liquidity = float(pair["liquidity"]["usd"])
    volume = float(pair["volume"]["h24"])

    if liquidity < CONFIG["MIN_LIQUIDITY"]:
        return

    if volume < CONFIG["MIN_VOLUME"]:
        return

    price = float(pair["priceUsd"])

    print(f"🚀 BUY {symbol}")

    ok = swap(WSOL, token, CONFIG["BUY_AMOUNT"])

    if not ok:
        return

    trade = {
        "token": token,
        "symbol": symbol,
        "buy_price": price,
        "time": time.time()
    }

    active_trades.append(trade)

    blacklist.add(token)
    seen_tokens.add(token)

    stats["trades"] += 1

    send(f"""
🚀 COMPRA

Token: {symbol}
Preço: ${price}

Liquidez: ${liquidity}
Volume: ${volume}
""")

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

    swap(token, WSOL, CONFIG["BUY_AMOUNT"])

    pnl = price / trade["buy_price"]

    if pnl >= 1:
        stats["wins"] += 1
    else:
        stats["losses"] += 1

    send(f"""
💰 VENDA

Token: {symbol}

Resultado: {round((pnl-1)*100,2)}%
""")

    active_trades.remove(trade)


# ================= MONITOR =================

def monitor(trade):

    start = time.time()

    while True:

        price = get_price(trade["token"])

        if not price:
            time.sleep(5)
            continue

        if price >= trade["buy_price"] * CONFIG["TAKE_PROFIT"]:
            sell(trade)
            return

        if price <= trade["buy_price"] * CONFIG["STOP_LOSS"]:
            sell(trade)
            return

        if time.time() - start > 1800:
            sell(trade)
            return

        time.sleep(5)


# ================= SCANNER =================

def scanner():

    while True:

        print("🔎 scanning...")

        url = "https://api.dexscreener.com/latest/dex/search?q=sol"

        data = safe_get(url)

        if not data:
            time.sleep(CONFIG["SCAN_INTERVAL"])
            continue

        pairs = data["pairs"]

        for pair in pairs:

            try:

                buy(pair)

            except:
                pass

        time.sleep(CONFIG["SCAN_INTERVAL"])


# ================= REPORT =================

def report():

    while True:

        time.sleep(7200)

        send(f"""
📊 RELATÓRIO

Trades: {stats["trades"]}
Wins: {stats["wins"]}
Losses: {stats["losses"]}

Ativos: {len(active_trades)}
""")


# ================= SERVER =================

app = Flask(__name__)

@app.route("/")
def home():
    return "bot running"


# ================= START =================

if __name__ == "__main__":

    send("🤖 SNIPER MEMECOIN INICIADO")

    threading.Thread(target=scanner).start()
    threading.Thread(target=report).start()

    app.run(host="0.0.0.0", port=10000)
