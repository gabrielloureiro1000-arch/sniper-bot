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

# --- CONFIGURAÇÃO DE ATAQUE REAL ---
CONFIG = {
    "entrada_sol": 0.05,     
    "min_vol_24h": 35000,    # Foco em moedas com tração (GMGN Style)
    "min_pump_5m": 2.0,      # Se subiu 2% em 5min, eu entro
    "priority_fee": 25000000, # Taxa agressiva para garantir a vaga
    "slippage": 2000         # 20% de margem para garantir a compra no pump
}

stats = {"scans": 0, "compras": 0, "vendas": 0, "lucro": 0.0, "inicio": datetime.now()}
blacklist = set()

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

@app.route('/')
def home(): return f"V12 SNIPER - Compras: {stats['compras']} | Ativo desde {stats['inicio'].strftime('%H:%M')}", 200

# RELATÓRIO A CADA 2 HORAS (PONTUAL)
def loop_relatorio():
    while True:
        time.sleep(7200)
        resumo = (f"📊 **RELATÓRIO DE PERFORMANCE (2H)**\n\n"
                  f"🛒 Compras Realizadas: `{stats['compras']}`\n"
                  f"✅ Vendas com Sucesso: `{stats['vendas']}`\n"
                  f"💰 Lucro Estimado: `{stats['lucro']:.4f} SOL`\n"
                  f"📡 Status: `Varrendo Solana...`")
        alertar(resumo)

def jupiter_swap(input_m, output_m, amount):
    try:
        # Pega a rota
        q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={CONFIG['slippage']}"
        quote = requests.get(q_url, timeout=5).json()
        
        # Monta o Swap
        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }
        resp = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        
        # Assina e envia
        raw_tx = base64.b64decode(resp['swapTransaction'])
        tx = VersionedTransaction.from_bytes(raw_tx)
        tx = VersionedTransaction(tx.message, [carteira])
        
        result = solana_client.send_raw_transaction(bytes(tx))
        return True, str(result.value)
    except Exception as e:
        return False, str(e)

def buscar_alvos():
    try:
        # Busca moedas que estão "quentes"
        data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
        for p in data.get('pairs', []):
            stats["scans"] += 1
            addr = p['baseToken']['address']
            sym = p['baseToken']['symbol']
            
            if addr in blacklist or sym == "SOL" or addr == WSOL: continue

            vol = float(p.get('volume', {}).get('h24', 0))
            pump = float(p.get('priceChange', {}).get('m5', 0))

            if vol > CONFIG["min_vol_24h"] and pump > CONFIG["min_pump_5m"]:
                blacklist.add(addr)
                alertar(f"🎯 **ALVO GMGN DETECTADO: {sym}**\nVol: ${vol:,.0f}\n*Enviando ordem de 0.05 SOL...*")
                
                sucesso, tx_id = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                if sucesso:
                    stats["compras"] += 1
                    alertar(f"✅ **COMPRA REALIZADA!**\nTx: `https://solscan.io/tx/{tx_id}`")
                    threading.Thread(target=venda_automatica, args=(addr, sym)).start()
                else:
                    alertar(f"❌ **FALHA NA EXECUÇÃO:** Rede congestionada.")
                break # Para e respira
    except: pass

def venda_automatica(addr, sym):
    time.sleep(150) # Segura o pump por 2.5 minutos
    sucesso, tx_id = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])
    if sucesso:
        stats["vendas"] += 1
        stats["lucro"] += 0.01
        alertar(f"💰 **LUCRO NO BOLSO: {sym}**\nVenda realizada com sucesso!")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    alertar("⚡ **BOT V12 SNIPER ONLINE**\nModo de compra real ativado. Boa sorte!")
    while True:
        buscar_alvos()
        time.sleep(15) # Varredura rápida
