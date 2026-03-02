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

# --- CONFIGURAÇÃO BERSERKER (MUITO AGRESSIVA) ---
CONFIG = {
    "entrada_sol": 0.01,
    "min_buys_1m": 3,          # APENAS 3 COMPRAS E ELE ENTRA
    "min_liq_usd": 500,        # QUALQUER LIQUIDEZ ELE ENTRA
    "take_profit": 1.10,       # BUSCA 10% E SAI
    "priority_fee": 200000000, # 0.20 SOL (TAXA PARA NÃO FALHAR)
    "slippage": 9900           # 99% (COMPRA A QUALQUER CUSTO)
}

stats = {"compras": 0, "lucro": 0.0, "analisados": 0}

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

@app.route('/')
def home(): return f"BERSERKER V25 - ANALISADOS: {stats['analisados']}", 200

def jupiter_swap(input_m, output_m, amount):
    try:
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={CONFIG['slippage']}"
        q = requests.get(url, timeout=5).json()
        payload = {"quoteResponse": q, "userPublicKey": str(carteira.pubkey()), "prioritizationFeeLamports": CONFIG["priority_fee"]}
        s = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        tx = VersionedTransaction.from_bytes(base64.b64decode(s['swapTransaction']))
        res = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(res.value)
    except Exception as e: return False, str(e)

def caçada_berserker():
    alertar("👺 **MODO BERSERKER ATIVADO**\nFiltros de segurança desativados. Atirando em tudo!")
    blacklist = set()
    while True:
        try:
            # Puxa os tokens mais recentes e ativos
            data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
            for pair in data.get('pairs', [])[:50]:
                stats["analisados"] += 1
                addr = pair['baseToken']['address']
                if addr in blacklist: continue
                
                m1_buys = int(pair.get('txns', {}).get('m1', {}).get('buys', 0))
                liq = float(pair.get('liquidity', {}).get('usd', 0))

                # GATILHO BERSERKER: Quase nada de trava
                if m1_buys >= CONFIG["min_buys_1m"] and liq >= CONFIG["min_liq_usd"]:
                    blacklist.add(addr)
                    alertar(f"🎯 **ALVO IDENTIFICADO: {pair['baseToken']['symbol']}**\nCompras/min: {m1_buys}\nGMGN: https://gmgn.ai/sol/token/{addr}")
                    
                    ok, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                    if ok:
                        stats["compras"] += 1
                        alertar(f"✅ **COMPRADO!** Tx: `{res}`")
                        # Gerencia saída rápido (Thread separada)
                        threading.Thread(target=saida_berserker, args=(addr,)).start()
                    else:
                        alertar(f"❌ **ERRO:** `{res[:50]}`")
        except: pass
        time.sleep(2)

def saida_berserker(addr):
    time.sleep(30) # Espera 30 segundos e tenta vender com lucro
    jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])
    alertar(f"💰 **VENDA TENTADA (TAKE PROFIT)**")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    caçada_berserker()
