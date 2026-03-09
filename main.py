```python
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

# ==============================
# ENV
# ==============================

RPC_URL = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY")
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

WSOL = "So11111111111111111111111111111111111111112"

# ==============================
# INIT
# ==============================

bot = telebot.TeleBot(TELEGRAM_TOKEN)
client = Client(RPC_URL)
wallet = Keypair.from_base58_string(PRIVATE_KEY)

# ==============================
# CONFIG
# ==============================

BUY_AMOUNT = 0.02

MIN_LIQ = 700
MIN_VOLUME = 150

TAKE_PROFIT = 2.5
STOP_LOSS = 0.65

MAX_TOKEN_AGE = 1200
MAX_TRADES = 4

SCAN_INTERVAL = 8

# ==============================
# STATE
# ==============================

active_trades = []
seen_tokens = set()

stats = {
    "trades":0,
    "wins":0,
    "losses":0,
    "profit":0
}

# ==============================
# TELEGRAM
# ==============================

def send(msg):
    try:
        bot.send_message(CHAT_ID,msg)
    except:
        pass

# ==============================
# HTTP
# ==============================

def safe_get(url):

    try:
        r=requests.get(url,timeout=10)

        if r.status_code!=200:
            return None

        return r.json()

    except:
        return None

# ==============================
# PRICE
# ==============================

def get_price(token):

    url=f"https://api.dexscreener.com/latest/dex/tokens/{token}"

    data=safe_get(url)

    if not data:
        return None

    pairs=data.get("pairs",[])

    if not pairs:
        return None

    return float(pairs[0]["priceUsd"])

# ==============================
# SWAP
# ==============================

def swap(input_mint,output_mint,amount):

    try:

        lamports=int(amount*1e9)

        quote=safe_get(
        f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={lamports}&slippageBps=2000"
        )

        if not quote:
            return False

        payload={
            "quoteResponse":quote,
            "userPublicKey":str(wallet.pubkey())
        }

        swap_tx=requests.post(
        "https://quote-api.jup.ag/v6/swap",
        json=payload).json()

        tx=VersionedTransaction.from_bytes(
        base64.b64decode(swap_tx["swapTransaction"])
        )

        signed=VersionedTransaction(tx.message,[wallet])

        client.send_raw_transaction(bytes(signed))

        return True

    except Exception as e:

        print("swap error",e)

        return False

# ==============================
# BUY
# ==============================

def buy(pair):

    base=pair["baseToken"]
    quote=pair["quoteToken"]

    base_addr=base["address"]
    symbol=base["symbol"]
    quote_addr=quote["address"]

    if quote_addr!=WSOL:
        return

    if base_addr==WSOL:
        return

    if base_addr in seen_tokens:
        return

    if len(active_trades)>=MAX_TRADES:
        return

    liquidity=float(pair["liquidity"]["usd"])
    volume=float(pair["volume"]["h24"])

    if liquidity<MIN_LIQ:
        return

    if volume<MIN_VOLUME:
        return

    created=pair.get("pairCreatedAt")

    if created:

        age=time.time()-(created/1000)

        if age>MAX_TOKEN_AGE:
            return

    price=float(pair["priceUsd"])

    print("🚀 BUY",symbol)

    ok=swap(WSOL,base_addr,BUY_AMOUNT)

    if not ok:
        return

    trade={
        "token":base_addr,
        "symbol":symbol,
        "buy_price":price,
        "time":time.time()
    }

    active_trades.append(trade)
    seen_tokens.add(base_addr)

    stats["trades"]+=1

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

# ==============================
# SELL
# ==============================

def sell(trade):

    token=trade["token"]
    symbol=trade["symbol"]

    price=get_price(token)

    if not price:
        return

    swap(token,WSOL,BUY_AMOUNT)

    pnl=price/trade["buy_price"]

    profit=(pnl-1)*100

    stats["profit"]+=profit

    if pnl>=1:
        stats["wins"]+=1
    else:
        stats["losses"]+=1

    send(f"""
💰 VENDA

Token: {symbol}

Resultado: {round(profit,2)}%
""")

    active_trades.remove(trade)

# ==============================
# MONITOR
# ==============================

def monitor(trade):

    start=time.time()

    while True:

        price=get_price(trade["token"])

        if not price:
            time.sleep(6)
            continue

        if price>=trade["buy_price"]*TAKE_PROFIT:
            sell(trade)
            return

        if price<=trade["buy_price"]*STOP_LOSS:
            sell(trade)
            return

        if time.time()-start>1800:
            sell(trade)
            return

        time.sleep(6)

# ==============================
# SCANNER
# ==============================

def scanner():

    while True:

        print("🔎 scanning...")

        data=safe_get(
        "https://api.dexscreener.com/latest/dex/pairs/solana"
        )

        if not data:
            time.sleep(SCAN_INTERVAL)
            continue

        pairs=data["pairs"]

        for pair in pairs[:200]:

            try:
                buy(pair)
            except:
                pass

        time.sleep(SCAN_INTERVAL)

# ==============================
# REPORT
# ==============================

def report():

    while True:

        time.sleep(7200)

        send(f"""
📊 RELATÓRIO 2H

Trades: {stats["trades"]}
Wins: {stats["wins"]}
Losses: {stats["losses"]}

Lucro acumulado: {round(stats["profit"],2)}%

Trades ativos: {len(active_trades)}
""")

# ==============================
# SERVER
# ==============================

app=Flask(__name__)

@app.route("/")
def home():
    return "sniper running"

# ==============================
# START
# ==============================

def start():

    send("🤖 SNIPER PROFISSIONAL ONLINE")

    threading.Thread(target=scanner,daemon=True).start()
    threading.Thread(target=report,daemon=True).start()

if __name__=="__main__":

    start()

    app.run(host="0.0.0.0",port=10000)
```
