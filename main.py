import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from datetime import datetime

# --- SETUP AMBIENTE ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)
WSOL = "So11111111111111111111111111111111111111112"

# --- CONFIGURAÇÃO RECALIBRADA (AGRESSIVO MAS ORGANIZADO) ---
CONFIG = {
    "entrada_sol": 0.05,     
    "min_vol_24h": 20000,    # Filtro para evitar moedas fantasmás
    "min_pump_5m": 1.5,      # Sinal de entrada real
    "priority_fee": 12000000, # Taxa alta para garantir a vaga
    "intervalo_scan": 20     # Pausa de 20s entre buscas para evitar spam
}

stats = {"scans": 0, "compras": 0, "vendas": 0, "lucro": 0.0, "inicio": datetime.now()}
blacklist = set() # Guarda moedas já detectadas para não repetir msg

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(f"Erro Telegram: {msg}")

@app.route('/')
def home(): 
    return f"V9.1 ANTI-SPAM - Ativo | Compras: {stats['compras']} | Lucro: {stats['lucro']:.4f}", 200

# RELATÓRIO DE 2 EM 2 HORAS
def loop_relatorio():
    while True:
        time.sleep(7200)
        msg = (f"📊 **RELATÓRIO DE OPERAÇÕES (2H)**\n\n"
               f"🔎 Varreduras: `{stats['scans']}`\n"
               f
