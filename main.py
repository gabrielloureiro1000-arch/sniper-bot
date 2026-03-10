import os
import time
import threading
import requests
import telebot
from flask import Flask

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

seen_tokens = set()
alerts_sent = 0

DEX_INTERVAL = 3
PUMP_INTERVAL = 6


def send(msg):
    global alerts_sent
    try:
        bot.send_message(CHAT_ID, msg, disable_web_page_preview=True)
        alerts_sent += 1
    except Exception as e:
        print("telegram error:", e)


# =========================
# SCAN DEXSCREENER
# =========================

def scan_dex():

    global seen_tokens

    while True:

        print("scanning dex")

        try:

            url = "https://api.dexscreener.com/latest/dex/pairs/solana"
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

                if token in seen_tokens:
                    continue

                liquidity = pair.get("liquidity", {}).get("usd", 0) or 0
                volume = pair.get("volume", {}).get("h24", 0) or 0

                buys = pair.get("txns", {}).get("h24", {}).get("buys", 0) or 0
                sells = pair.get("txns", {}).get("h24", {}).get("sells", 0) or 0

                tx = buys + sells

                # filtros corrigidos para detectar cedo
                if liquidity < 30:
                    continue

                if tx < 2:
                    continue

                seen_tokens.add(token)

                gmgn = f"https://gmgn.ai/sol/token/{token}"
                dex = f"https://dexscreener.com/solana/{token}"

                msg = f"""
🚨 MEMECOIN DETECTADA

Token: {symbol}

Liquidez: ${round(liquidity)}
Volume 24h: ${round(volume)}
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


# =========================
# SCAN PUMPFUN
# =========================

def scan_pump():

    global seen_tokens

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

                if token in seen_tokens:
                    continue

                seen_tokens.add(token)

                gmgn = f"https://gmgn.ai/sol/token/{token}"

                msg = f"""
🔥 NOVO TOKEN PUMPFUN

Token: {symbol}

Analisar rápido:

GMGN
{gmgn}
"""

                send(msg)

        except Exception as e:
            print("pump error:", e)

        time.sleep(PUMP_INTERVAL)


# =========================
# RELATÓRIO
# =========================

def report():

    global alerts_sent

    while True:

        time.sleep(7200)

        msg = f"""
📊 RELATÓRIO DO BOT

Tokens detectados: {len(seen_tokens)}
Alertas enviados: {alerts_sent}

Status: ONLINE
"""

        send(msg)


# =========================
# SERVER
# =========================

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
