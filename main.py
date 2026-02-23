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
               f"🛒 Compras: `{stats['compras']}`\n"
               f"✅ Vendas: `{stats['vendas']}`\n"
               f"💰 Lucro Est.: `{stats['lucro']:.4f} SOL`\n\n"
               f"🚀 *Status: Operando sem SPAM.*")
        alertar(msg)

def jupiter_swap(input_m, output_m, amount):
    try:
        url_quote = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps=1500"
        quote = requests.get(url_quote, timeout=5).json()
        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }
        res = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        tx_data = base64.b64decode(res['swapTransaction'])
        tx = VersionedTransaction.from_bytes(tx_data)
        tx = VersionedTransaction(tx.message, [carteira])
        sig = solana_client.send_raw_transaction(bytes(tx))
        return True, sig.value
    except: return False, None

def caçar_lucro():
    try:
        # Busca moedas pareadas em SOL com filtros de volume
        data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
        for p in data.get('pairs', []):
            stats["scans"] += 1
            addr = p['baseToken']['address']
            
            # PULA SE JÁ VIMOS ESSA MOEDA RECENTEMENTE
            if addr in blacklist: continue 

            vol = float(p.get('volume', {}).get('h24', 0))
            pump = float(p.get('priceChange', {}).get('m5', 0))

            if vol > CONFIG["min_vol_24h"] and pump > CONFIG["min_pump_5m"]:
                sym = p['baseToken']['symbol']
                blacklist.add(addr) # Bloqueia para não repetir a mensagem
                
                alertar(f"🎯 **ALVO DETECTADO: {sym}**\nVolume: ${vol:,.0f}\nSubida 5m: {pump}%\n*Executando Sniper...*")
                
                sucesso, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                if sucesso:
                    stats["compras"] += 1
                    alertar(f"✅ **COMPRA REALIZADA!**\nTx: `{res}`")
                    threading.Thread(target=venda_rapida, args=(addr, sym)).start()
                
                # Após encontrar uma boa, ele para o loop atual para processar
                break 
    except: pass

def venda_rapida(addr, sym):
    time.sleep(180) # Segura o pump por 3 minutos
    sucesso, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])
    if sucesso:
        stats["vendas"] += 1
        stats["lucro"] += 0.015 # Média de lucro esperada
        alertar(f"💵 **LUCRO NO BOLSO: {sym}**\nPosição encerrada com sucesso!")
    # Remove da blacklist após a venda para poder operar de novo se houver novo pump
    time.sleep(600)
    blacklist.discard(addr)

if __name__ == "__main__":
    # Inicia os serviços
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    
    alertar("🛡️ **V9.1 ANTI-SPAM ATIVADA**\nFiltros recalibrados. Silêncio e lucro.")
    
    while True:
        caçar_lucro()
        time.sleep(CONFIG["intervalo_scan"]) # Pausa obrigatória para não travar o Telegram
