import requests
import time
import os
import telebot
import threading
from flask import Flask

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

seen_tokens = set()

SCAN_INTERVAL = 3


def send(msg):
    try:
        bot.send_message(CHAT_ID, msg, disable_web_page_preview=True)
    except Exception as e:
        print("telegram error:", e)


def scan_dex():

    global seen_tokens

    while True:

        print("scanning dex")

        try:

            url = "https://api.dexscreener.com/latest/dex/pairs/solana"
            r = requests.get(url, timeout=10)

            if r.status_code != 200:
                time.sleep(SCAN_INTERVAL)
                continue

            data = r.json()

            pairs = data.get("pairs", [])

            for pair in pairs:

                base = pair.get("baseToken", {})
                token = base.get("address")
                symbol = base.get("symbol", "UNKNOWN")

                if not token:
                    continue

                if token in seen_tokens:
                    continue

                liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
                volume = pair.get("volume", {}).get("h24", 0) or 0

                buys = pair.get("txns", {}).get("h24", {}).get("buys", 0) or 0
                sells = pair.get("txns", {}).get("h24", {}).get("sells", 0) or 0

                tx = buys + sells

                if liquidity < 200:
                    continue

                if tx < 5:
                    continue

                seen_tokens.add(token)

                gmgn = f"https://gmgn.ai/sol/token/{token}"
                dex = f"https://dexscreener.com/solana/{token}"

                msg = f"""
🚨 TOKEN DETECTADO

Token: {symbol}

Liquidez: ${round(liquidity)}
Volume: ${round(volume)}
Transações: {tx}

GMGN
{gmgn}

Dexscreener
{dex}
"""

                send(msg)

        except Exception as e:
            print("dex error:", e)

        time.sleep(SCAN_INTERVAL)


def scan_pump():

    global seen_tokens

    while True:

        print("scanning pump")

        try:

            url = "https://frontend-api.pump.fun/coins/latest"
            r = requests.get(url, timeout=10)

            if r.status_code != 200:
                time.sleep(5)
                continue

            data = r.json()

            for coin in data:

                token = coin.get("mint")
                name = coin.get("symbol")

                if not token:
                    continue

                if token in seen_tokens:
                    continue

                seen_tokens.add(token)

                gmgn = f"https://gmgn.ai/sol/token/{token}"

                msg = f"""
🔥 NOVO TOKEN PUMPFUN

Token: {name}

ANALISAR

GMGN
{gmgn}
"""

                send(msg)

        except Exception as e:
            print("pump error:", e)

        time.sleep(10)


def report():

    while True:

        time.sleep(7200)

        msg = f"""
📊 RELATÓRIO

Tokens monitorados: {len(seen_tokens)}

Status: ONLINE
"""

        send(msg)


app = Flask(__name__)


@app.route("/")
def home():
    return "sniper running"


def start():

    send("🚀 SNIPER MEMECOIN ONLINE")

    threading.Thread(target=scan_dex).start()
    threading.Thread(target=scan_pump).start()
    threading.Thread(target=report).start()


if __name__ == "__main__":

    start()

    port = int(os.environ.get("PORT", 10000))

    app.run(host="0.0.0.0", port=port)
