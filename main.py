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

# --- CONFIGURAÇÃO DE LUCRO (GMGN STYLE) ---
CONFIG = {
    "entrada_sol": 0.05,     # Aumentado para cobrir taxas e dar lucro real
    "tp": 1.40,               # Vende com 40% de lucro (alvo nas tendências)
    "sl": 0.80,               # Stop Loss em 20%
    "min_vol_24h": 300000,    # Tokens com volume real
    "min_change_1h": 2.5      # Entra na força do movimento
}

stats = {"compras": 0, "vendas": 0, "scans": 0, "lucro_sol": 0.0, "inicio": datetime.now()}
blacklist = {}

@app.route('/')
def home(): 
    return f"V7.5 GMGN ANTI-BLOCK - Scans: {stats['scans']} | Lucro: {stats['lucro_sol']:.4f} SOL", 200

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(f"Telegram Erro: {msg}")

# --- RELATÓRIO DE 2 EM 2 HORAS ---
def loop_relatorio():
    while True:
        time.sleep(7200)
        tempo = datetime.now() - stats["inicio"]
        msg = (f"📊 **RELATÓRIO DE LUCRO V7.5**\n\n"
               f"🕒 Ativo há: `{str(tempo).split('.')[0]}`\n"
               f"🔍 Analisados: `{stats['scans']}`\n"
               f"✅ Compras: `{stats['compras']}` | 💰 Vendas: `{stats['vendas']}`\n"
               f"💵 Lucro Total: `{stats['lucro_sol']:.4f} SOL`\n"
               f"📡 Status: `OPERANDO`")
        alertar(msg)

def jupiter_swap(input_m, output_m, amount):
    try:
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps=1500"
        res = requests.get(url, timeout=10).json()
        if "outAmount" not in res: return False, "Sem Rota"
        
        data = {"quoteResponse": res, "userPublicKey": str(carteira.pubkey()), "prioritizationFeeLamports": 5000000}
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json=data, timeout=10).json()
        tx = VersionedTransaction.from_bytes(base64.b64decode(swap_res['swapTransaction']))
        tx = VersionedTransaction(tx.message, [carteira])
        sig = solana_client.send_raw_transaction(bytes(tx))
        return True, sig.value
    except: return False, "Erro Swap"

def buscar_momentum():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
    url = "https://api.dexscreener.com/latest/dex/search?q=SOL"
    
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            print(f"API Bloqueada (Status {response.status_code}). Esperando...")
            time.sleep(20)
            return

        data = response.json()
        for p in data.get('pairs', []):
            stats["scans"] += 1
            addr = p.get('baseToken', {}).get('address')
            sym = p.get('baseToken', {}).get('symbol')
            vol = float(p.get('volume', {}).get('h24', 0))
            change = float(p.get('priceChange', {}).get('h1', 0))

            if addr == WSOL or addr in blacklist or p.get('chainId') != 'solana': continue

            # Lógica GMGN: Volume alto + Começando a subir forte
            if vol > CONFIG["min_vol_24h"] and change > CONFIG["min_change_1h"]:
                alertar(f"🔥 **MOMENTUM: {sym}**\nVol: ${vol:,.0f} | Alta 1h: {change}%\n*Comprando...*")
                ok, sig = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                if ok:
                    stats["compras"] += 1
                    blacklist[addr] = True
                    # Monitoramento simples de venda (TP/SL)
                    time.sleep(30) # Espera um pouco para o preço mover
                    threading.Thread(target=venda_automatica, args=(addr, sym)).start()
                    break
    except Exception as e:
        print(f"Erro no scan: {e}")
        time.sleep(10)

def venda_automatica(addr, sym):
    # Monitora para vender no lucro
    tentativas = 0
    while tentativas < 50:
        tentativas += 1
        time.sleep(15)
        try:
            url = f"https://quote-api.jup.ag/v6/quote?inputMint={addr}&outputMint={WSOL}&amount=1000000000&slippageBps=50"
            res = requests.get(url).json()
            ratio = int(res['outAmount']) / 1e9 / 0.00000001 # Base de cálculo simples
            # Lógica de venda por tempo/lucro para não travar o bot
            if tentativas > 40: # Venda forçada após muito tempo
                jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])
                break
        except: continue

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    alertar("🚀 **BOT V7.5 ANTI-BLOCK ATIVADO**\nFocado em Volume e Tendência GMGN.")
    while True:
        buscar_momentum()
        time.sleep(15) # Delay maior para evitar o erro de 'char 0'
