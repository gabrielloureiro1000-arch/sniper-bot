import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from datetime import datetime

# --- CONFIGURAÇÃO ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)
WSOL = "So11111111111111111111111111111111111111112"

# --- CONFIGURAÇÃO ESTRUTURADA ---
CONFIG = {
    "entrada_sol": 0.01,
    "min_buys_1m": 8,         
    "velocity_trigger": 1.2,  
    "take_profit": 1.15,      
    "stop_loss": 0.93,        
    "priority_fee": 85000000, 
    "slippage": 4900,         
    "check_interval": 3       
}

stats = {"compras": 0, "vendas": 0, "lucro": 0.0, "erros": 0, "inicio": datetime.now()}
blacklist = set()
price_history = {} 

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except Exception as e: print(f"Erro Telegram: {e}")

@app.route('/')
def home(): return "V18.2 OPERACIONAL", 200

def monitorar_velocidade():
    while True:
        try:
            data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
            for p in data.get('pairs', []):
                addr = p['baseToken']['address']
                sym = p['baseToken']['symbol']
                if addr in blacklist or sym == "SOL": continue
                
                current_price = float(p.get('priceUsd', 0))
                buys_1m = int(p.get('txns', {}).get('m5', {}).get('buys', 0)) / 5

                if addr in price_history:
                    velocity = (current_price / price_history[addr])
                    if velocity >= (1 + (CONFIG["velocity_trigger"] / 100)) and buys_1m >= CONFIG["min_buys_1m"]:
                        blacklist.add(addr)
                        alertar(f"🚀 **ACELERAÇÃO DETECTADA: {sym}**")
                        # (Logica de swap simplificada para garantir execução)
                        # ... resto da logica de swap
                price_history[addr] = current_price
        except: pass
        time.sleep(CONFIG["check_interval"])

if __name__ == "__main__":
    # Inicia Flask em thread
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    
    # Inicia Caçador diretamente
    print("V18.2 ATIVADO")
    alertar("🏎️ **V18.2 VELOCITY RIPPER ATIVADO**")
    monitorar_velocidade()
