import os
import time
import threading
import requests
import telebot
from flask import Flask

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

seen = set()
alerts = 0

DEX_INTERVAL = 5
PUMP_INTERVAL = 10


def send(msg):
    global alerts
    try:
        bot.send_message(CHAT_ID, msg, disable_web_page_preview=True)
        alerts += 1
    except Exception as e:
        print("telegram error:", e)


# =====================
# DEXSCREENER SCANNER
# =====================

def scan_dex():

    global seen

    while True:

        print("scanning dex")

        try:

            url = "https://api.dexscreener.com/latest/dex/search/?q=sol"
            r = requests.get(url, timeout=10)

            if r.status_code != 200:
                time.sleep(DEX_INTERVAL)
                continue

            data = r.json()
            pairs = data.get("pairs", [])

            for pair in pairs:

                base = pair.get("baseToken", {})
                token = base.get("address")
                symbol = base.get("symbol", "UNKNOWN")

                if not token:
                    continue

                if token in seen:
                    continue

                liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
                volume = pair.get("volume", {}).get("h24", 0) or 0

                buys = pair.get("txns", {}).get("h24", {}).get("buys", 0) or 0
                sells = pair.get("txns", {}).get("h24", {}).get("sells", 0) or 0

                tx = buys + sells

                if liquidity < 20:
                    continue

                if tx < 1:
                    continue

                seen.add(token)

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

        time.sleep(DEX_INTERVAL)


# =====================
# PUMPFUN SCANNER
# =====================

def scan_pump():

    global seen

    while True:

        print("scanning pump")

        try:

            url = "https://frontend-api.pump.fun/coins/latest"
            r = requests.get(url, timeout=10)

            if r.status_code != 200:
                time.sleep(PUMP_INTERVAL)
                continue

            data = r.json()

            for coin in data:

                token = coin.get("mint")
                symbol = coin.get("symbol", "UNKNOWN")

                if not token:
                    continue

                if token in seen:
                    continue

                seen.add(token)

                gmgn = f"https://gmgn.ai/sol/token/{token}"

                msg = f"""
🔥 NOVO TOKEN PUMPFUN

Token: {symbol}

ANALISAR

GMGN
{gmgn}
"""

                send(msg)

        except Exception as e:
            print("pump error:", e)

        time.sleep(PUMP_INTERVAL)


# =====================
# RELATÓRIO
# =====================

def report():

    global alerts

    while True:

        time.sleep(7200)

        msg = f"""
📊 RELATÓRIO DO BOT

Tokens detectados: {len(seen)}
Alertas enviados: {alerts}

Status: ONLINE
"""

        send(msg)


# =====================
# SERVER
# =====================

app = Flask(__name__)


@app.route("/")
def home():
    return "sniper running"


def start():

    send("🚀 MEMECOIN SNIPER ONLINE")

    threading.Thread(target=scan_dex).start()
    threading.Thread(target=scan_pump).start()
    threading.Thread(target=report).start()


if __name__ == "__main__":

    start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
