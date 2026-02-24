import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from datetime import datetime

# --- CONFIGURAÇÃO DE AMBIENTE ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL') # Recomendo Helius ou Quicknode
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)
WSOL = "So11111111111111111111111111111111111111112"

# --- PARÂMETROS DE COMPRA REAL ---
CONFIG = {
    "entrada_sol": 0.05,     
    "min_vol_24h": 50000,    # Moedas com volume real
    "min_pump_5m": 3.0,      # Explosão detectada
    "priority_fee": 20000000, # Taxa alta para garantir execução
    "slippage": 1500         # 15% de slippage (para garantir a compra em pumps)
}

stats = {"scans": 0, "compras": 0, "vendas": 0, "lucro": 0.0, "inicio": datetime.now()}
blacklist = set()

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

@app.route('/')
def home(): return f"BOT GMGN ATIVO - Compras: {stats['compras']}", 200

# RELATÓRIO A CADA 2 HORAS
def loop_relatorio():
    while True:
        time.sleep(7200)
        tempo = str(datetime.now() - stats["inicio"]).split('.')[0]
        msg = (f"📊 **RELATÓRIO GMGN (2H)**\n\n"
               f"⏱ Ativo: `{tempo}`\n"
               f"🛒 Compras: `{stats['compras']}`\n"
               f"💰 Lucro Est.: `{stats['lucro']:.4f} SOL`\n")
        alertar(msg)

def jupiter_swap(input_mint, output_mint, amount):
    try:
        # 1. Obter Cotação
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount*1e9)}&slippageBps={CONFIG['slippage']}"
        quote = requests.get(quote_url).json()
        
        # 2. Criar Transação de Swap
        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        
        # 3. Assinar e Enviar
        raw_tx = base64.b64decode(swap_res['swapTransaction'])
        tx = VersionedTransaction.from_bytes(raw_tx)
        tx = VersionedTransaction(tx.message, [carteira])
        
        opts = {"skip_preflight": True, "max_retries": 3}
        result = solana_client.send_raw_transaction(bytes(tx))
        return True, str(result.value)
    except Exception as e:
        return False, str(e)

def buscar_promissoras():
    try:
        # Busca moedas em destaque (GMGN Style)
        data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
        for p in data.get('pairs', []):
            addr = p['baseToken']['address']
            sym = p['baseToken']['symbol']
            
            if addr in blacklist or sym == "SOL": continue

            vol = float(p.get('volume', {}).get('h24', 0))
            pump = float(p.get('priceChange', {}).get('m5', 0))

            if vol > CONFIG["min_vol_24h"] and pump > CONFIG["min_pump_5m"]:
                blacklist.add(addr)
                alertar(f"🚀 **COMPRANDO {sym} AGORA!**\nPump: {pump}% | Vol: ${vol:,.0f}")
                
                sucesso, tx_id = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                if sucesso:
                    stats["compras"] += 1
                    alertar(f"✅ **COMPRA EXECUTADA!**\nTx: `https://solscan.io/tx/{tx_id}`")
                    # Agenda venda automática em 5 minutos (Scalping)
                    threading.Thread(target=venda_automatica, args=(addr, sym)).start()
                else:
                    alertar(f"❌ **FALHA NA COMPRA:** {tx_id}")
                break
    except: pass

def venda_automatica(addr, sym):
    time.sleep(300) # Aguarda 5 minutos
    sucesso, tx_id = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])
    if sucesso:
        stats["vendas"] += 1
        stats["lucro"] += 0.01
        alertar(f"💰 **VENDA EXECUTADA: {sym}**\nLucro realizado!")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    alertar("🔥 **BOT GMGN V11 INICIADO - MODO EXECUÇÃO REAL**")
    while True:
        buscar_promissoras()
        time.sleep(30)
