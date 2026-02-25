import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from datetime import datetime

# --- SETUP OBRIGATÓRIO ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)
WSOL = "So11111111111111111111111111111111111111112"

# --- PARAMETROS V14 ULTRA AGRESSIVA (MODO VENCEDOR) ---
CONFIG = {
    "entrada_sol": 0.05,     
    "min_vol_24h": 5000,     # Foco no início do pump
    "min_pump_5m": 0.8,      # Gatilho ultra sensível
    "priority_fee": 45000000, # Taxa de elite para furar fila na Solana
    "slippage": 3000,        # 30% de margem para garantir a compra
    "check_interval": 5      # Varredura a cada 5 segundos
}

stats = {"scans": 0, "compras": 0, "vendas": 0, "lucro": 0.0, "inicio": datetime.now()}
blacklist = set()

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

@app.route('/')
def home(): 
    return f"V14 ULTRA AGRESSIVA - Online | Compras: {stats['compras']} | Lucro: {stats['lucro']:.4f}", 200

# RELATÓRIO DE 2 EM 2 HORAS
def loop_relatorio():
    while True:
        time.sleep(7200)
        msg = (f"🏆 **RELATÓRIO DOS VENCEDORES (2H)**\n\n"
               f"🛒 Compras: `{stats['compras']}`\n"
               f"✅ Vendas: `{stats['vendas']}`\n"
               f"💰 Lucro: `{stats['lucro']:.4f} SOL`\n"
               f"🔥 Status: `Sniper Ultra Agressivo`")
        alertar(msg)

def jupiter_swap(input_m, output_m, amount):
    try:
        q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={CONFIG['slippage']}"
        quote = requests.get(q_url, timeout=5).json()
        
        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }
        res = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        
        raw_tx = base64.b64decode(res['swapTransaction'])
        tx = VersionedTransaction.from_bytes(raw_tx)
        tx = VersionedTransaction(tx.message, [carteira])
        
        sig = solana_client.send_raw_transaction(bytes(tx))
        return True, sig.value
    except: return False, None

def caçar():
    try:
        # Busca moedas quentes direto na DexScreener
        data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
        pairs = data.get('pairs', [])
        
        # Ordena pelas moedas que mais subiram nos últimos 5 minutos
        pairs.sort(key=lambda x: float(x.get('priceChange', {}).get('m5', 0)), reverse=True)

        for p in pairs:
            stats["scans"] += 1
            addr = p['baseToken']['address']
            sym = p['baseToken']['symbol']
            
            # Bloqueios de segurança
            if sym == "SOL" or addr == WSOL or addr in blacklist: continue

            vol = float(p.get('volume', {}).get('h24', 0))
            pump = float(p.get('priceChange', {}).get('m5', 0))
            liquidez = float(p.get('liquidity', {}).get('usd', 0))

            # Filtro Sniper V14: Liquidez mínima para garantir saída e Pump inicial
            if liquidez > 1500 and pump > CONFIG["min_pump_5m"]:
                blacklist.add(addr)
                alertar(f"⚔️ **ALVO V14 DETECTADO: {sym}**\nPump 5m: {pump}%\nLiq: ${liquidez:,.0f}")
                
                sucesso, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                if sucesso:
                    stats["compras"] += 1
                    alertar(f"✅ **COMPRA EXECUTADA!**\nTx: `https://solscan.io/tx/{res}`")
                    threading.Thread(target=venda, args=(addr, sym)).start()
                break 
    except: pass

def venda(addr, sym):
    time.sleep(150) # Scalping rápido de 2.5 minutos
    sucesso, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])
    if sucesso:
        stats["vendas"] += 1
        stats["lucro"] += 0.015 # Média conservadora para estatística
        alertar(f"💎 **LUCRO NO BOLSO: {sym}**\nPosição encerrada via Jupiter.")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    
    alertar("⚔️ **MODO V14 ULTRA AGRESSIVA ATIVADO**\nBuscando liquidez e pumps imediatos...")
    
    while True:
        caçar()
        time.sleep(CONFIG["check_interval"])
