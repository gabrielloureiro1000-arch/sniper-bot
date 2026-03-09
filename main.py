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

RPC_URL=os.getenv("RPC_URL")
PRIVATE_KEY=os.getenv("WALLET_PRIVATE_KEY")
TELEGRAM_TOKEN=os.getenv("TELEGRAM_TOKEN")
CHAT_ID=os.getenv("CHAT_ID")

WSOL="So11111111111111111111111111111111111111112"

bot=telebot.TeleBot(TELEGRAM_TOKEN)
client=Client(RPC_URL)
wallet=Keypair.from_base58_string(PRIVATE_KEY)

BUY_AMOUNT=0.02

MIN_LIQ=200
MIN_VOLUME=20
MAX_TOKEN_AGE=600

TAKE_PROFIT=3
STOP_LOSS=0.65

MAX_TRADES=6
SCAN_INTERVAL=4

active_trades=[]
seen_tokens=set()

stats={
"buys":0,
"sells":0,
"profit":0
}

def tg(msg):
    try:
        bot.send_message(CHAT_ID,msg)
    except:
        pass

def http(url):
    try:
        r=requests.get(url,timeout=8)
        if r.status_code!=200:
            return None
        return r.json()
    except:
        return None

def price(token):

    url=f"https://api.dexscreener.com/latest/dex/tokens/{token}"
    data=http(url)

    if not data:
        return None

    pairs=data.get("pairs",[])

    if not pairs:
        return None

    return float(pairs[0]["priceUsd"])

def swap(input_mint,output_mint,amount):

    try:

        lamports=int(amount*1e9)

        quote=http(
        f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={lamports}&slippageBps=2500"
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

def buy(pair):

    base=pair["baseToken"]
    quote=pair["quoteToken"]

    token=base["address"]
    symbol=base["symbol"]

    if quote["address"]!=WSOL:
        return

    if token in seen_tokens:
        return

    if len(active_trades)>=MAX_TRADES:
        return

    liq=float(pair["liquidity"]["usd"])
    vol=float(pair["volume"]["h24"])

    if liq<MIN_LIQ:
        return

    if vol<MIN_VOLUME:
        return

    created=pair.get("pairCreatedAt")

    if created:
        age=time.time()-(created/1000)

        if age>MAX_TOKEN_AGE:
            return

    p=float(pair["priceUsd"])

    print("BUY",symbol)

    ok=swap(WSOL,token,BUY_AMOUNT)

    if not ok:
        return

    trade={
    "token":token,
    "symbol":symbol,
    "buy_price":p,
    "time":time.time()
    }

    active_trades.append(trade)
    seen_tokens.add(token)

    stats["buys"]+=1

    tg(f"🚀 COMPRA {symbol}\npreço ${p}\nliq ${liq}")

    threading.Thread(target=monitor,args=(trade,),daemon=True).start()

def sell(trade):

    token=trade["token"]
    symbol=trade["symbol"]

    p=price(token)

    if not p:
        return

    swap(token,WSOL,BUY_AMOUNT)

    pnl=p/trade["buy_price"]
    gain=(pnl-1)*100

    stats["profit"]+=gain
    stats["sells"]+=1

    tg(f"💰 VENDA {symbol}\nresultado {round(gain,2)}%")

    active_trades.remove(trade)

def monitor(trade):

    start=time.time()

    while True:

        p=price(trade["token"])

        if not p:
            time.sleep(5)
            continue

        if p>=trade["buy_price"]*TAKE_PROFIT:
            sell(trade)
            return

        if p<=trade["buy_price"]*STOP_LOSS:
            sell(trade)
            return

        if time.time()-start>1800:
            sell(trade)
            return

        time.sleep(5)

def scan_dex():

    while True:

        data=http("https://api.dexscreener.com/latest/dex/pairs/solana")

        if data:

            for pair in data["pairs"][:300]:

                try:
                    buy(pair)
                except:
                    pass

        time.sleep(SCAN_INTERVAL)

def report():

    while True:

        time.sleep(7200)

        tg(f"""📊 RELATÓRIO 2H

compras: {stats['buys']}
vendas: {stats['sells']}
lucro acumulado: {round(stats['profit'],2)}%

trades ativos: {len(active_trades)}
""")

app=Flask(__name__)

@app.route("/")
def home():
    return "ultra sniper running"

def start():

    tg("🤖 ULTRA SNIPER ONLINE")

    threading.Thread(target=scan_dex,daemon=True).start()
    threading.Thread(target=report,daemon=True).start()

if __name__=="__main__":

    start()

    app.run(host="0.0.0.0",port=10000)
