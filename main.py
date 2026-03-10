import requests
import time
import os
import telebot
from flask import Flask
import threading

TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

bot = telebot.TeleBot(TELEGRAM_TOKEN)

# tokens já enviados
seen_tokens = {}

SCAN_INTERVAL = 5

# filtros
MIN_LIQUIDITY = 500
MIN_TX = 3
MAX_TOKEN_AGE = 3600

alerts_sent = 0


def send(msg):
    global alerts_sent
    try:
        bot.send_message(CHAT_ID, msg, disable_web_page_preview=True)
        alerts_sent += 1
    except Exception as e:
        print("telegram error", e)


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

                    liquidity = pair["liquidity"]["usd"]
                    tx = pair["txns"]["h24"]["buys"] + pair["txns"]["h24"]["sells"]

                    created = pair.get("pairCreatedAt", 0)
                    age = int(time.time() * 1000) - created

                    if token in seen_tokens:
                        continue

                    if liquidity < MIN_LIQUIDITY:
                        continue

                    if tx < MIN_TX:
                        continue

                    if age > MAX_TOKEN_AGE * 1000:
                        continue

                    seen_tokens[token] = True

                    gmgn = f"https://gmgn.ai/sol/token/{token}"
                    dex = f"https://dexscreener.com/solana/{token}"

                    msg = f"""
🚨 NOVO TOKEN DETECTADO

Token: {name}

Liquidez: ${round(liquidity)}
Transações: {tx}

Idade: {round(age/60000)} minutos

🔎 ANALISAR:

GMGN
{gmgn}

Dexscreener
{dex}
"""

                    send(msg)

                except Exception as e:
                    print("pair error", e)

        except Exception as e:
            print("scan error", e)

        time.sleep(SCAN_INTERVAL)


def report():

    while True:

        time.sleep(7200)

        msg = f"""
📊 RELATÓRIO 2 HORAS

Scanner ativo

Tokens analisados: {len(seen_tokens)}
Alertas enviados: {alerts_sent}

Status: ONLINE
"""

        send(msg)


app = Flask(__name__)


@app.route("/")
def home():
    return "memecoin scanner running"


def start():

    send("🤖 MEMECOIN SCANNER INICIADO")

    threading.Thread(target=scan, daemon=True).start()
    threading.Thread(target=report, daemon=True).start()


if __name__ == "__main__":

    start()

    app.run(host="0.0.0.0", port=10000)
