import os
import time
import threading
import requests
import base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- SETUP AMBIENTE ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)

# --- PARÂMETROS DE EXECUÇÃO ---
CONFIG = {
    "entrada_sol": 0.01,
    "tp": 1.70,            # +70% Lucro
    "sl": 0.75,            # -25% Stop Loss
    "trailing_dist": 0.05, # Segue o preço com 5% de distância
    "min_liq": 1200,       # Liquidez mínima em USD
    "min_vol_5m": 5000     # Volume mínimo nos últimos 5 min para tokens sem social
}

stats = {"compras": 0, "vendas": 0, "lucro_sol": 0.0}
blacklist = {} 

session = requests.Session()
retries = Retry(total=2, backoff_factor=0.1)
session.mount('https://', HTTPAdapter(max_retries=retries))

@app.route('/')
def home(): return "SNIPER V6.1 - VOLUME & SOCIAL - ATIVO", 200

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

def jupiter_swap(input_m, output_m, amount, slippage=3500):
    try:
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m
