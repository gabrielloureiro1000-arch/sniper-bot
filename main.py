import requests
import time
import os
import telebot
from flask import Flask
import threading

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

seen_tokens = set()

SCAN_INTERVAL = 4

alerts = 0


def send(msg):
    global alerts
    try:
        bot.send_message(CHAT_ID, msg, disable_web_page_preview=True)
        alerts += 1
    except Exception as e:
        print("telegram error:", e)


def scan():

    while True:

        print("scanning")

        try:

            url = "https://api.dexscreener.com/latest/dex/pairs/solana"
            r = requests.get(url, timeout=10)

            if r.status_code != 200:
                time.sleep(SCAN_INTERVAL)
                continue

            data = r.json()

            for pair in data["pairs"]:

                try:

                    token = pair["baseToken"]["address"]
                    name = pair["baseToken"]["symbol"]

                    if token in seen_tokens:
                        continue

                    liquidity = pair["liquidity"]["usd"]
                    buys = pair["txns"]["h24"]["buys"]
                    sells = pair["txns"]["h24"]["sells"]

                    tx = buys + sells

                    # filtros mínimos (bem baixos para pegar memecoin cedo)
                    if liquidity < 100:
                        continue

                    if tx < 1:
                        continue

                    seen_tokens.add(token)

                    gmgn = f"https://gmgn.ai/sol/token/{token}"
                    dex = f"https://dexscreener.com/solana/{token}"

                    msg = f"""
🚨 NOVO TOKEN

Token: {name}

Liquidez: ${round(liquidity)}
Transações: {tx}

🔎 ANALISAR

GMGN
{gmgn}

Dexscreener
{dex}
"""

                    send(msg)

                except:
                    pass

        except Exception as e:
            print("scan error:", e)

        time.sleep(SCAN_INTERVAL)


def report():

    while True:

        time.sleep(7200)

        msg = f"""
📊 RELATÓRIO 2 HORAS

Scanner ativo

Tokens detectados: {len(seen_tokens)}
Alertas enviados: {alerts}
"""

        send(msg)


app = Flask(__name__)


@app.route("/")
def home():
    return "scanner running"


def start():

    send("🤖 MEMECOIN SCANNER ONLINE")

    threading.Thread(target=scan, daemon=True).start()
    threading.Thread(target=report, daemon=True).start()


if __name__ == "__main__":

    start()

    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
