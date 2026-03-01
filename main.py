import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

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

# --- CONFIGURAÇÃO AGRESSIVA ---
CONFIG = {
    "entrada_sol": 0.01,
    "priority_fee": 150000000, # 0.15 SOL (Taxa de Guerra - Entra ou Entra)
    "slippage": 5000,          # 50%
    "min_volume_24h": 50000    # Pelo menos 50k de volume para não cair em golpe vazio
}

@app.route('/')
def home(): return "STORM BREAKER V23 - BUSCANDO...", 200

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(f"TELEGRAM_ERROR: {msg}")

def jupiter_swap(input_m, output_m, amount):
    try:
        # 1. Pegar Quote
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={CONFIG['slippage']}"
        quote = requests.get(url, timeout=5).json()
        
        if "error" in quote:
            return False, f"Erro Jupiter: {quote['error']}"

        # 2. Criar Transação
        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }
        resp_swap = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        
        raw_tx = base64.b64decode(resp_swap['swapTransaction'])
        tx = VersionedTransaction.from_bytes(raw_tx)
        
        # 3. Enviar para a Rede
        res = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(res.value)
    except Exception as e:
        return False, str(e)

def caçar_e_destruir():
    print("🚀 SCANNER INICIADO...")
    blacklist = set()
    
    while True:
        try:
            # Puxa moedas em alta (Trending) na Solana
            url = "https://api.geckoterminal.com/api/v2/networks/solana/trending_pools"
            data = requests.get(url, timeout=10).json()
            
            for pool in data.get('data', []):
                attr = pool.get('attributes', {})
                addr = attr.get('address')
                base_token_addr = pool['relationships']['base_token']['data']['id'].split('_')[1]
                name = attr.get('name')
                vol = float(attr.get('volume_usd', {}).get('h24', 0))

                if base_token_addr in blacklist or base_token_addr == WSOL: continue

                # CRITÉRIO DE BALEIA: Volume alto e movimento recente
                if vol > CONFIG["min_volume_24h"]:
                    blacklist.add(base_token_addr)
                    
                    gmgn_link = f"https://gmgn.ai/sol/token/{base_token_addr}"
                    alertar(f"🔥 **BALEIA DETECTADA EM {name}**\nVolume 24h: `${vol:,.0f}`\n🔗 [Analisar na GMGN]({gmgn_link})\n\n⚡ *Enviando Ordem...*")
                    
                    ok, res = jupiter_swap(WSOL, base_token_addr, CONFIG["entrada_sol"])
                    
                    if ok:
                        alertar(f"✅ **COMPRA ENVIADA!**\nTx: `https://solscan.io/tx/{res}`")
                    else:
                        alertar(f"❌ **FALHA CRÍTICA:**\n`{res}`")
                    break # Faz uma pausa após detectar um alvo
        except Exception as e:
            print(f"Erro no Loop: {e}")
        
        time.sleep(5) # Delay entre scans para evitar bloqueio de IP

if __name__ == "__main__":
    # Roda o Flask em uma thread
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    # Roda o Caçador na thread principal
    caçar_e_destruir()
