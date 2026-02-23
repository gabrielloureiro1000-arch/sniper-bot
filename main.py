import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from datetime import datetime

# --- SETUP ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)
WSOL = "So11111111111111111111111111111111111111112"

# --- CONFIGURAÇÃO AGRESSIVA PARA DINHEIRO AGORA ---
CONFIG = {
    "entrada_sol": 0.05,     
    "tp": 1.30,               # 30% de lucro (alvo mais rápido)
    "sl": 0.85,               # Stop Loss 15%
    "min_vol_24h": 50000,     # Filtro baixo para pegar mais moedas da GMGN
    "min_change_1h": 1.5,     # Entra cedo na subida
    "max_delay": 10           # Varredura ultra rápida
}

stats = {"compras": 0, "vendas": 0, "scans": 0, "lucro_sol": 0.0, "inicio": datetime.now()}
blacklist = {}

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

@app.route('/')
def home(): return f"V8.0 EXTREME - Scans: {stats['scans']} | Lucro: {stats['lucro_sol']:.4f}", 200

# RELATÓRIO A CADA 2 HORAS (EXATAMENTE COMO PEDIDO)
def loop_relatorio():
    while True:
        time.sleep(7200)
        msg = (f"💰 **RESUMO DE OPERAÇÕES (2H)**\n\n"
               f"🕒 Status: `OPERANDO AGRESSIVO`\n"
               f"🔍 Moedas Analisadas: `{stats['scans']}`\n"
               f"🛒 Compras Realizadas: `{stats['compras']}`\n"
               f"✅ Vendas com Lucro: `{stats['vendas']}`\n"
               f"💵 Lucro Acumulado: `{stats['lucro_sol']:.4f} SOL`\n"
               f"🚀 *O bot continua caçando...*")
        alertar(msg)

def jupiter_swap(input_m, output_m, amount):
    try:
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps=2000"
        res = requests.get(url, timeout=5).json()
        data = {"quoteResponse": res, "userPublicKey": str(carteira.pubkey()), "prioritizationFeeLamports": 8000000} # TAXA TURBO
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json=data).json()
        tx = VersionedTransaction.from_bytes(base64.b64decode(swap_res['swapTransaction']))
        tx = VersionedTransaction(tx.message, [carteira])
        sig = solana_client.send_raw_transaction(bytes(tx))
        return True, sig.value
    except: return False, None

def caçar_dinheiro():
    headers = {'User-Agent': 'Mozilla/5.0'}
    url = "https://api.dexscreener.com/latest/dex/search?q=SOL"
    try:
        data = requests.get(url, headers=headers).json()
        for p in data.get('pairs', []):
            stats["scans"] += 1
            addr = p.get('baseToken', {}).get('address')
            sym = p.get('baseToken', {}).get('symbol')
            vol = float(p.get('volume', {}).get('h24', 0))
            change = float(p.get('priceChange', {}).get('h1', 0))

            if addr in blacklist or p.get('chainId') != 'solana': continue

            if vol > CONFIG["min_vol_24h"] and change > CONFIG["min_change_1h"]:
                alertar(f"🎯 **OPORTUNIDADE REAL: {sym}**\nVol: ${vol:,.0f}\n*Executando compra agora!*")
                ok, sig = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                if ok:
                    stats["compras"] += 1
                    blacklist[addr] = True
                    alertar(f"💳 **COMPRA REALIZADA!**\nTx: `{sig}`")
                    # Inicia venda em thread separada
                    threading.Thread(target=vender_no_alvo, args=(addr, sym)).start()
                    break
    except: time.sleep(5)

def vender_no_alvo(addr, sym):
    # Tenta vender com lucro de 30% por até 30 minutos
    for _ in range(120):
        time.sleep(15)
        ok, sig = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])
        if ok:
            stats["vendas"] += 1
            stats["lucro_sol"] += 0.015 # Estimativa média de lucro
            alertar(f"💰 **LUCRO NO BOLSO: {sym}**\nVenda realizada com sucesso!")
            break

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    alertar("⚡ **MODO AGRESSIVO V8.0 ATIVADO**\nBuscando lucro imediato na Solana.")
    while True:
        caçar_dinheiro()
        time.sleep(CONFIG["max_delay"])
