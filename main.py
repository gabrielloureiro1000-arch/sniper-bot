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

# --- CONFIGURAÇÃO MOMENTUM (Para capturar altas como as da imagem) ---
CONFIG = {
    "entrada_sol": 0.02,     # Aumentei um pouco para valer a pena a taxa
    "tp": 1.25,               # Alvo de 25% de lucro rápido
    "sl": 0.85,               # Stop Loss em 15%
    "min_vol_24h": 500000,    # Garante que o token tem liquidez real (como SXP/AGLD)
    "min_change_1h": 3.0      # Só entra se estiver subindo pelo menos 3% na última hora
}

stats = {"compras": 0, "vendas": 0, "scans": 0, "lucro_estimado": 0, "inicio": datetime.now()}
blacklist = []

@app.route('/')
def home(): 
    return f"V7.0 GMGN HUNTER - Scans: {stats['scans']} | Lucro: {stats['lucro_estimado']} SOL", 200

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

# --- RELATÓRIO COMPLETO A CADA 2 HORAS ---
def loop_relatorio():
    while True:
        time.sleep(7200)
        tempo = datetime.now() - stats["inicio"]
        msg = (f"📈 **RELATÓRIO DE PERFORMANCE V7.0**\n\n"
               f"⏱️ Tempo de Execução: `{str(tempo).split('.')[0]}`\n"
               f"🔍 Ativos Analisados: `{stats['scans']}`\n"
               f"🛒 Compras: `{stats['compras']}` | ✅ Vendas: `{stats['vendas']}`\n"
               f"💰 Lucro Estimado: `{stats['lucro_estimado']:.4f} SOL`\n"
               f"📡 Status: `BUSCANDO MOMENTUM`")
        alertar(msg)

def jupiter_swap(input_m, output_m, amount):
    try:
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps=1000"
        quote = requests.get(url).json()
        data = {"quoteResponse": quote, "userPublicKey": str(carteira.pubkey()), "prioritizationFeeLamports": 5000000}
        res = requests.post("https://quote-api.jup.ag/v6/swap", json=data).json()
        tx = VersionedTransaction.from_bytes(base64.b64decode(res['swapTransaction']))
        tx = VersionedTransaction(tx.message, [carteira])
        sig = solana_client.send_raw_transaction(bytes(tx))
        return True, sig.value
    except: return False, None

def monitorar_tendencia(addr, sym, p_compra):
    alertar(f"👀 Monitorando tendência de {sym}...")
    while True:
        time.sleep(10)
        # Simulação de preço via Quote (mais rápido que esperar indexação)
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={addr}&outputMint={WSOL}&amount=1000000000&slippageBps=50"
        try:
            res = requests.get(url).json()
            p_atual = int(res['outAmount']) / 1e9
            lucro = p_atual / p_compra # Simplificado para lógica de ratio
            
            if lucro >= CONFIG["tp"] or lucro <= CONFIG["sl"]:
                ok, sig = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"]) # Vende o equivalente
                if ok:
                    stats["vendas"] += 1
                    stats["lucro_estimado"] += (p_atual - p_compra)
                    alertar(f"💰 **VENDA REALIZADA: {sym}**\nResultado: {((lucro-1)*100):.2f}%")
                    break
        except: continue

def buscar_momentum_gmgn():
    # Usamos a API do DexScreener filtrando por maior volume/ganho para simular o radar da GMGN
    url = "https://api.dexscreener.com/latest/dex/search?q=SOL"
    try:
        data = requests.get(url).json()
        for p in data.get('pairs', []):
            stats["scans"] += 1
            change = float(p.get('priceChange', {}).get('h1', 0))
            vol = float(p.get('volume', {}).get('h24', 0))
            addr = p.get('baseToken', {}).get('address')
            sym = p.get('baseToken', {}).get('symbol')

            if addr in blacklist or p.get('chainId') != 'solana': continue

            # Lógica: Se tem volume alto (SXP/AGLD style) e está subindo forte agora
            if vol > CONFIG["min_vol_24h"] and change > CONFIG["min_change_1h"]:
                alertar(f"🔥 **MOMENTUM DETECTADO: {sym}**\nVolume 24h: ${vol:,.0f}\nAlta 1h: {change}%\n*Iniciando Compra...*")
                ok, sig = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                if ok:
                    stats["compras"] += 1
                    blacklist.append(addr)
                    threading.Thread(target=monitorar_tendencia, args=(addr, sym, CONFIG["entrada_sol"])).start()
                    break
    except Exception as e:
        print(f"Erro scan: {e}")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    alertar("🦅 **BOT V7.0 GMGN HUNTER ONLINE**\nFocado em tokens com alta tração e volume.")
    while True:
        buscar_momentum_gmgn()
        time.sleep(30) # Varredura a cada 30s para não levar rate limit
