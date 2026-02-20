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
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

# --- SETUP AMBIENTE ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)

# --- CONSTANTES ---
WSOL = "So11111111111111111111111111111111111111112"

# --- PARÂMETROS DE EXECUÇÃO ---
CONFIG = {
    "entrada_sol": 0.01,
    "tp": 1.70,            
    "sl": 0.75,            
    "trailing_dist": 0.05, 
    "min_liq": 1200,       
    "min_vol_5m": 3000     # Aumentei a sensibilidade para 3k
}

blacklist = {} 
session = requests.Session()
session.mount('https://', HTTPAdapter(max_retries=Retry(total=2, backoff_factor=0.1)))

@app.route('/')
def home(): return "SNIPER V6.2 - OPERACIONAL", 200

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

def jupiter_swap(input_m, output_m, amount, slippage=3500):
    try:
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slippage}"
        quote = session.get(url, timeout=5).json()
        if "outAmount" not in quote: return False, "Sem Rota"

        data = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": 6000000 
        }
        res = session.post("https://quote-api.jup.ag/v6/swap", json=data, timeout=7).json()
        
        raw_tx = base64.b64decode(res['swapTransaction'])
        tx = VersionedTransaction.from_bytes(raw_tx)
        tx = VersionedTransaction(tx.message, [carteira])
        
        sig = solana_client.send_raw_transaction(bytes(tx))
        return True, {"sig": sig.value, "out": int(quote["outAmount"])/1e9}
    except Exception as e: return False, str(e)

def gerenciar_venda(addr, sym, p_entrada):
    max_p = p_entrada
    while True:
        time.sleep(2)
        ok, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"]) 
        if not ok: continue
        
        p_atual = res["out"]
        lucro = p_atual / CONFIG["entrada_sol"]
        if lucro > max_p: max_p = lucro

        vender = False
        if lucro >= CONFIG["tp"] or lucro <= CONFIG["sl"]: vender = True
        elif lucro > 1.10 and lucro < (max_p * (1 - CONFIG["trailing_dist"])): vender = True

        if vender:
            v_ok, v_res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], slippage=5000)
            if v_ok:
                alertar(f"💰 **VENDA: {sym}** | Lucro: {((lucro-1)*100):.1f}%")
                break

def sniper_main():
    alertar("🦅 **SNIPER V6.2 INICIADO**\nFiltrando SOL nativo | Scan Ativo")
    while True:
        try:
            # Busca focada em tokens pareados com SOL
            r = session.get(f"https://api.dexscreener.com/latest/dex/tokens/{WSOL}", timeout=5).json()
            pairs = r.get('pairs', [])
            
            for p in pairs:
                addr = p.get('baseToken', {}).get('address')
                sym = p.get('baseToken', {}).get('symbol')
                liq = float(p.get('liquidity', {}).get('usd', 0))
                vol_5m = float(p.get('volume', {}).get('m5', 0))
                info = p.get('info', {})

                # Filtros de Segurança
                if addr == WSOL or addr in blacklist or p.get('chainId') != 'solana':
                    continue

                tem_social = any([info.get('socials'), info.get('websites')])
                volume_ok = vol_5m > CONFIG["min_vol_5m"]

                if liq >= CONFIG["min_liq"] and (tem_social or volume_ok):
                    print(f"✅ ALVO QUALIFICADO: {sym}")
                    ok, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                    
                    if ok:
                        alertar(f"🚀 **COMPRA: {sym}**\nTX: `https://solscan.io/tx/{res['sig']}`")
                        gerenciar_venda(addr, sym, CONFIG["entrada_sol"])
                        break
                    else:
                        blacklist[addr] = time.time() + 120
            
            time.sleep(3) 
        except: time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    sniper_main()
