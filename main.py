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

# --- PARÂMETROS DE ELITE ---
CONFIG = {
    "entrada_sol": 0.01,
    "min_volume_m5": 8000,    # Volume mínimo de $8k em 5min (Filtra lixo)
    "min_liq": 5000,          # Liquidez mínima de $5k
    "priority_fee": 120000000,# 0.12 SOL (Taxa de Predador)
    "slippage": 5000          # 50%
}

stats = {"compras": 0, "vendas": 0, "lucro": 0.0, "erros": 0}
blacklist = set()

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=False)
    except: print(msg)

@app.route('/')
def home(): return "ORACLE EYE V22 - BUSCANDO BALEIAS", 200

def loop_relatorio():
    while True:
        time.sleep(7200)
        alertar(f"📊 **RELATÓRIO PERIÓDICO**\nCompras: {stats['compras']}\nLucro Acumulado: {stats['lucro']:.4f} SOL")

def jupiter_swap(input_m, output_m, amount):
    try:
        q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={CONFIG['slippage']}"
        res_q = requests.get(q_url, timeout=5).json()
        if "error" in res_q: return False, f"Sem Rota: {res_q['error']}"

        payload = {"quoteResponse": res_q, "userPublicKey": str(carteira.pubkey()), "prioritizationFeeLamports": CONFIG["priority_fee"]}
        res_s = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        
        tx = VersionedTransaction.from_bytes(base64.b64decode(res_s['swapTransaction']))
        sig = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(sig.value)
    except Exception as e: return False, str(e)

def analisar_e_comprar():
    while True:
        try:
            # Puxa tokens com maior atividade (Boosted)
            data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
            for pair in data.get('pairs', [])[:25]:
                addr = pair['baseToken']['address']
                sym = pair['baseToken']['symbol']
                
                if addr in blacklist or sym == "SOL": continue
                
                vol_m5 = float(pair.get('volume', {}).get('m5', 0))
                liq = float(pair.get('liquidity', {}).get('usd', 0))
                m5_tx = pair.get('txns', {}).get('m5', {})
                buys = m5_tx.get('buys', 0)
                sells = m5_tx.get('sells', 0)

                # FILTRO PROMISSOR: Volume alto + Pressão de Compra + Liquidez mínima
                if vol_m5 > CONFIG["min_volume_m5"] and buys > (sells * 2) and liq > CONFIG["min_liq"]:
                    blacklist.add(addr)
                    
                    gmgn_link = f"https://gmgn.ai/sol/token/{addr}"
                    
                    alertar(f"💎 **TOKEN PROMISSOR DETECTADO!**\n\n"
                           f"📌 **Nome:** {sym}\n"
                           f"📊 **Volume (5m):** `${vol_m5:,.0f}`\n"
                           f"🔥 **Pressão:** {buys}B / {sells}S\n"
                           f"🔗 **Análise GMGN:** [CLIQUE AQUI]({gmgn_
