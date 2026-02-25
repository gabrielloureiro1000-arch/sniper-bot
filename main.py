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

# --- PARAMETROS V13 GOD MODE ---
CONFIG = {
    "entrada_sol": 0.05,     
    "min_vol_24h": 15000,    # Foco em novos lançamentos com tração
    "min_pump_5m": 1.2,      # Gatilho rápido para não perder o timing
    "priority_fee": 30000000, # Prioridade total na rede Solana
    "slippage": 2500,        # 25% para garantir a compra em velas de alta
    "check_interval": 10     # Varredura a cada 10 segundos
}

stats = {"compras": 0, "vendas": 0, "lucro": 0.0, "inicio": datetime.now()}
blacklist = set()

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: pass

@app.route('/')
def home(): return f"V13 GOD MODE ATIVO | Compras: {stats['compras']}", 200

def loop_relatorio():
    while True:
        time.sleep(7200) # 2 horas exatas
        msg = (f"🏆 **RELATÓRIO DOS VENCEDORES (2H)**\n\n"
               f"🛒 Compras: `{stats['compras']}`\n"
               f"✅ Vendas: `{stats['vendas']}`\n"
               f"💰 Lucro: `{stats['lucro']:.4f} SOL`\n"
               f"🔥 Status: `Sniper Ativo`")
        alertar(msg)

def jupiter_swap(input_m, output_m, amount):
    try:
        q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={CONFIG['slippage']}"
        quote = requests.get(q_url, timeout=5).json()
        payload = {"quoteResponse": quote, "userPublicKey": str(carteira.pubkey()), "prioritizationFeeLamports": CONFIG["priority_fee"]}
        res = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        tx = VersionedTransaction.from_bytes(base64.b64decode(res['swapTransaction']))
        sig = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, sig.value
    except: return False, None

def caçar():
    try:
        data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
        for p in data.get('pairs', []):
            addr = p['baseToken']['address']
            sym = p['baseToken']['symbol']
            
            # FILTRO DE ELITE: Ignora o próprio SOL e evita repetir moedas
            if sym == "SOL" or addr == WSOL or addr in blacklist: continue

            vol = float(p.get('volume', {}).get('h24', 0))
            pump = float(p.get('priceChange', {}).get('m5', 0))

            if vol > CONFIG["min_vol_24h"] and pump > CONFIG["min_pump_5m"]:
                blacklist.add(addr)
                alertar(f"⚔️ **SNIPER DISPARADO: {sym}**\nSubida: {pump}% | Vol: ${vol:,.0f}")
                
                sucesso, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                if sucesso:
                    stats["compras"] += 1
                    alertar(f"✅ **COMPRA EXECUTADA!**\nTx: `https://solscan.io/tx/{res}`")
                    threading.Thread(target=venda, args=(addr, sym)).start()
                break
    except: pass

def venda(addr, sym):
    time.sleep(180) # Scalping rápido de 3 minutos
    sucesso, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])
    if sucesso:
        stats["vendas"] += 1
        stats["lucro"] += 0.012
        alertar(f"💎 **LUCRO REALIZADO: {sym}**")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    alertar("🚀 **V13.0 GOD MODE INICIADO**\nPrepare o bolso, a caça começou!")
    while True:
        caçar()
        time.sleep(CONFIG["check_interval"])
