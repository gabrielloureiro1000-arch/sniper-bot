import os
import time
import asyncio
import base64
import requests
import telebot

from flask import Flask
from solana.rpc.websocket_api import connect
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction


RPC = os.getenv("RPC_URL")
PRIVATE_KEY = os.getenv("WALLET_PRIVATE_KEY")
TELEGRAM = os.getenv("TELEGRAM_TOKEN")
CHAT = os.getenv("CHAT_ID")

WSOL = "So11111111111111111111111111111111111111112"

bot = telebot.TeleBot(TELEGRAM)

client = Client(RPC)

wallet = Keypair.from_base58_string(PRIVATE_KEY)

BUY_AMOUNT = 0.02

TAKE_PROFIT = 2.0
STOP_LOSS = 0.6

MIN_LIQ = 3000

active = []
seen = set()


def send(msg):
    try:
        bot.send_message(CHAT, msg)
    except:
        pass


def price(token):

    url = f"https://api.dexscreener.com/latest/dex/tokens/{token}"

    r = requests.get(url)

    if r.status_code != 200:
        return None

    data = r.json()

    if not data["pairs"]:
        return None

    return float(data["pairs"][0]["priceUsd"])


def swap(input_mint, output_mint, amount):

    lamports = int(amount * 1e9)

    q = requests.get(
        f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={lamports}&slippageBps=1500"
    ).json()

    if not q:
        return False

    payload = {
        "quoteResponse": q,
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


def buy(token):

    if token in seen:
        return

    seen.add(token)

    p = price(token)

    if not p:
        return

    ok = swap(WSOL, token, BUY_AMOUNT)

    if not ok:
        return

    trade = {
        "token": token,
        "buy": p
    }

    active.append(trade)

    send(f"🚀 BUY {token}\nprice ${p}")

    asyncio.create_task(monitor(trade))


def sell(trade):

    p = price(trade["token"])

    swap(trade["token"], WSOL, BUY_AMOUNT)

    pnl = p / trade["buy"]

    send(f"💰 SELL {trade['token']} {round((pnl-1)*100,2)}%")

    active.remove(trade)


async def monitor(trade):

    start = time.time()

    while True:

        p = price(trade["token"])

        if not p:
            await asyncio.sleep(5)
            continue

        if p >= trade["buy"] * TAKE_PROFIT:
            sell(trade)
            return

        if p <= trade["buy"] * STOP_LOSS:
            sell(trade)
            return

        if time.time() - start > 1800:
            sell(trade)
            return

        await asyncio.sleep(5)


async def raydium_listener():

    async with connect(RPC) as ws:

        await ws.logs_subscribe()

        while True:

            msg = await ws.recv()

            logs = str(msg)

            if "initialize2" in logs:

                token = logs.split("mint")[1][:44]

                buy(token)


def report():

    while True:

        time.sleep(7200)

        send(f"""
📊 REPORT

Active trades: {len(active)}
Tokens seen: {len(seen)}
""")


app = Flask(__name__)


@app.route("/")
def home():
    return "sniper running"


def start():

    send("🤖 PROFESSIONAL SNIPER ONLINE")

    loop = asyncio.new_event_loop()

    asyncio.set_event_loop(loop)

    loop.create_task(raydium_listener())

    loop.run_forever()


if __name__ == "__main__":

    import threading

    threading.Thread(target=start).start()

    threading.Thread(target=report).start()

    app.run(host="0.0.0.0", port=10000)
