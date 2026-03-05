import os
import time
import threading
import requests
import base64

import telebot

from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

from flask import Flask

# ---------------- CONFIG ----------------

TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY")

WSOL = "So11111111111111111111111111111111111111112"

CONFIG = {
    "trade_amount_sol": 0.02,
    "min_liquidity_usd": 5000,
    "min_volume_usd": 2000,
    "take_profit": 1.4,
    "stop_loss": 0.75,
    "max_hold_minutes": 10,
    "scan_interval": 8,
    "slippage_bps": 1200,
    "priority_fee": 1000000
}

HEADERS = {
    "User-Agent": "Mozilla/5.0"
}

# ---------------- INIT ----------------

bot = telebot.TeleBot(TOKEN)

solana_client = Client(RPC_URL)
wallet = Keypair.from_base58_string(PRIVATE_KEY)

blacklist = set()
active_trades = []

stats = {
    "wins": 0,
    "losses": 0,
    "trades": 0
}

# ---------------- SAFE REQUEST ----------------

def safe_get_json(url):

    try:

        r = requests.get(url, headers=HEADERS, timeout=10)

        if r.status_code != 200:
            print("HTTP error", r.status_code)
            return None

        if not r.text:
            return None

        return r.json()

    except Exception as e:

        print("request error", e)

        return None


# ---------------- TELEGRAM ----------------

def alert(msg):

    try:

        bot.send_message(
            CHAT_ID,
            msg,
            parse_mode="Markdown",
            disable_web_page_preview=True
        )

    except Exception as e:

        print("telegram error", e)


# ---------------- JUPITER SWAP ----------------

def jupiter_swap(input_mint, output_mint, amount):

    try:

        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount*1e9)}&slippageBps={CONFIG['slippage_bps']}"

        quote = safe_get_json(url)

        if not quote:
            return False, None

        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(wallet.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }

        swap = requests.post(
            "https://quote-api.jup.ag/v6/swap",
            json=payload,
            headers=HEADERS,
            timeout=10
        ).json()

        tx = VersionedTransaction.from_bytes(
            base64.b64decode(swap["swapTransaction"])
        )

        signed = VersionedTransaction(tx.message, [wallet])

        sig = solana_client.send_raw_transaction(bytes(signed))

        return True, str(sig.value)

    except Exception as e:

        print("swap error", e)

        return False, None


# ---------------- PRICE ----------------

def get_price(token):

    try:

        url = f"https://api.dexscreener.com/latest/dex/tokens/{token}"

        data = safe_get_json(url)

        if not data:
            return None

        pairs = data.get("pairs", [])

        if not pairs:
            return None

        return float(pairs[0]["priceUsd"])

    except:

        return None


# ---------------- FILTER ----------------

def valid_pair(pair):

    try:

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


# ---------------- BUY ----------------

def buy_token(pair):

    token = pair["baseToken"]["address"]
    symbol = pair["baseToken"]["symbol"]

    print("🚀 buying", symbol)

    ok, tx = jupiter_swap(
        WSOL,
        token,
        CONFIG["trade_amount_sol"]
    )

    if not ok:
        return

    price = float(pair["priceUsd"])

    trade = {
        "token": token,
        "symbol": symbol,
        "buy_price": price,
        "buy_time": time.time()
    }

    active_trades.append(trade)

    stats["trades"] += 1

    alert(
        f"🚀 *COMPRA*\n\n"
        f"Token: {symbol}\n"
        f"Preço: ${price}\n"
        f"https://solscan.io/tx/{tx}"
    )

    threading.Thread(
        target=monitor_trade,
        args=(trade,),
        daemon=True
    ).start()


# ---------------- SELL ----------------

def sell_token(trade):

    token = trade["token"]
    symbol = trade["symbol"]

    ok, tx = jupiter_swap(
        token,
        WSOL,
        CONFIG["trade_amount_sol"]
    )

    if not ok:
        return

    price = get_price(token)

    if not price:
        return

    pnl = price / trade["buy_price"]

    if pnl >= 1:
        stats["wins"] += 1
    else:
        stats["losses"] += 1

    alert(
        f"💰 *VENDA*\n\n"
        f"Token: {symbol}\n"
        f"Resultado: {round((pnl-1)*100,2)}%\n"
        f"https://solscan.io/tx/{tx}"
    )

    active_trades.remove(trade)


# ---------------- MONITOR ----------------

def monitor_trade(trade):

    start = time.time()

    while True:

        price = get_price(trade["token"])

        if not price:
            time.sleep(4)
            continue

        if price >= trade["buy_price"] * CONFIG["take_profit"]:
            sell_token(trade)
            return

        if price <= trade["buy_price"] * CONFIG["stop_loss"]:
            sell_token(trade)
            return

        if time.time() - start > CONFIG["max_hold_minutes"] * 60:
            sell_token(trade)
            return

        time.sleep(4)


# ---------------- SCANNER ----------------

def scan_tokens():

    while True:

        try:

            print("🔎 scanning...")

            url = "https://api.dexscreener.com/latest/dex/search?q=SOL"

            data = safe_get_json(url)

            if not data:
                time.sleep(10)
                continue

            pairs = data.get("pairs", [])

            for pair in pairs[:40]:

                token = pair["baseToken"]["address"]

                if token in blacklist:
                    continue

                if not valid_pair(pair):
                    continue

                blacklist.add(token)

                buy_token(pair)

        except Exception as e:

            print("scan error", e)

        time.sleep(CONFIG["scan_interval"])


# ---------------- REPORT ----------------

def report_loop():

    while True:

        time.sleep(7200)

        msg = (
            "📊 *RELATÓRIO BOT*\n\n"
            f"Trades: {stats['trades']}\n"
            f"Vitórias: {stats['wins']}\n"
            f"Perdas: {stats['losses']}\n"
            f"Trades ativos: {len(active_trades)}"
        )

        alert(msg)


# ---------------- SERVER (RENDER FIX) ----------------

app = Flask(__name__)

@app.route("/")
def home():
    return "Bot running"


def run_server():
    app.run(host="0.0.0.0", port=10000)


# ---------------- START ----------------

if __name__ == "__main__":

    alert("🐙 BOT SNIPER INICIADO")

    threading.Thread(target=run_server, daemon=True).start()
    threading.Thread(target=scan_tokens, daemon=True).start()
    threading.Thread(target=report_loop, daemon=True).start()

    while True:
        time.sleep(60)
