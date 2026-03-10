import requests
import time
import os
import telebot
from flask import Flask
import threading

TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")

bot=telebot.TeleBot(TELEGRAM_TOKEN)

seen=set()

SCAN_INTERVAL=5

def send(msg):

    try:
        bot.send_message(CHAT_ID,msg,disable_web_page_preview=True)
    except:
        pass

def http(url):

    try:
        r=requests.get(url,timeout=10)
        if r.status_code!=200:
            return None
        return r.json()
    except:
        return None

def score(liq,vol,tx):

    s=0

    if liq>5000:
        s+=3
    elif liq>1000:
        s+=2
    else:
        s+=1

    if vol>10000:
        s+=3
    elif vol>2000:
        s+=2
    else:
        s+=1

    if tx>200:
        s+=3
    elif tx>80:
        s+=2
    else:
        s+=1

    return round((s/9)*10,1)

def scan():

    while True:

        print("scanning")

        data=http("https://api.dexscreener.com/latest/dex/pairs/solana")

        if data:

            for pair in data["pairs"][:300]:

                try:

                    token=pair["baseToken"]["address"]

                    if token in seen:
                        continue

                    seen.add(token)

                    name=pair["baseToken"]["symbol"]

                    liq=float(pair["liquidity"]["usd"])

                    vol=float(pair["volume"]["h24"])

                    tx=pair["txns"]["h24"]["buys"]+pair["txns"]["h24"]["sells"]

                    sc=score(liq,vol,tx)

                    gmgn=f"https://gmgn.ai/sol/token/{token}"

                    dex=f"https://dexscreener.com/solana/{token}"

                    msg=f"""
🚨 NEW TOKEN

Token: {name}

Liquidity: ${round(liq)}
Volume: ${round(vol)}
Transactions: {tx}

Score: {sc}/10

GMGN
{gmgn}

Dexscreener
{dex}
"""

                    send(msg)

                except:
                    pass

        time.sleep(SCAN_INTERVAL)

def report():

    while True:

        time.sleep(7200)

        send("📊 Scanner ativo nas últimas 2 horas")

app=Flask(__name__)

@app.route("/")
def home():
    return "scanner running"

def start():

    send("🤖 MEMECOIN SCANNER ONLINE")

    threading.Thread(target=scan,daemon=True).start()
    threading.Thread(target=report,daemon=True).start()

if __name__=="__main__":

    start()

    app.run(host="0.0.0.0",port=10000)
