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

# --- CONFIGURAÇÕES ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)

# --- CONFIGURAÇÕES DE ELITE ---
CONFIG = {
    "entrada_sol": 0.01,
    "tp": 1.60,            # +60% Lucro (Ousado)
    "sl": 0.78,            # -22% Prejuízo
    "trailing_dist": 0.06, # Trailing stop de 6%
    "min_liq": 1500,       # BAIXADO: Para pegar o início do pump
    "min_vol_1h": 2500,    # Foco em tokens que acabaram de acordar
}

stats = {"compras": 0, "vendas": 0, "lucro_sol": 0.0, "erros": 0}
blacklist = {} 
start_time = time.time()

session = requests.Session()
retries = Retry(total=2, backoff_factor=0.3, status_forcelist=[429, 500])
session.mount('https://', HTTPAdapter(max_retries=retries))

@app.route('/')
def home(): return "SNIPER ELITE V5 ONLINE", 200

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

def jupiter_swap(input_m, output_m, amount, slippage=3000): # Slippage 30% para garantir
    try:
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slippage}"
        quote = session.get(url, timeout=7).json()
        if "outAmount" not in quote: return False, "Sem Rota Jupiter"

        data = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": 5000000 # PRIORIDADE ELITE (0.005 SOL)
        }
        res = session.post("https://quote-api.jup.ag/v6/swap", json=data, timeout=10).json()
        
        raw_tx = base64.b64decode(res['swapTransaction'])
        tx = VersionedTransaction.from_bytes(raw_tx)
        tx = VersionedTransaction(tx.message, [carteira])
        
        sig = solana_client.send_raw_transaction(bytes(tx))
        return True, {"sig": sig.value, "out": int(quote["outAmount"])/1e9}
    except Exception as e:
        return False, str(e)

def gerenciar_saida(addr, symbol, p_entrada):
    max_p = p_entrada
    SOL = "So11111111111111111111111111111111111111112"
    
    while True:
        time.sleep(3) # Monitoramento agressivo
        ok, res = jupiter_swap(addr, SOL, CONFIG["entrada_sol"]) 
        if not ok: continue
        
        p_atual = res["out"]
        lucro = p_atual / CONFIG["entrada_sol"]
        if lucro > max_p: max_p = lucro

        vender = False
        motivo = ""
        if lucro >= CONFIG["tp"]: vender, motivo = True, "💰 ALVO ATINGIDO (TP)"
        elif lucro <= CONFIG["sl"]: vender, motivo = True, "⚠️ PROTEÇÃO ATIVADA (SL)"
        elif lucro > 1.15 and lucro < (max_p * (1 - CONFIG["trailing_dist"])):
            vender, motivo = True, "🛡️ TRAILING STOP"

        if vender:
            v_ok, v_res = jupiter_swap(addr, SOL, CONFIG["entrada_sol"], slippage=4000)
            if v_ok:
                stats["vendas"] += 1
                stats["lucro_sol"] += (p_atual - CONFIG["entrada_sol"])
                alertar(f"✅ **VENDA EXECUTADA: {symbol}**\nResultado: {((lucro-1)*100):.1f}% | {motivo}")
                break

def sniper_elite():
    alertar("🛸 **SNIPER ELITE V5 - MODO CAÇADOR**\nMonitorando lançamentos e tendências...")
    SOL = "So11111111111111111111111111111111111111112"
    
    while True:
        try:
            # Pegando os tokens mais promissores no momento
            r = session.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=8).json()
            pairs = r.get('pairs', [])
            
            for p in pairs:
                addr = p.get('baseToken', {}).get('address')
                sym = p.get('baseToken', {}).get('symbol')
                liq = float(p.get('liquidity', {}).get('usd', 0))
                vol = float(p.get('volume', {}).get('h1', 0))

                if addr in blacklist or p.get('chainId') != 'solana': continue

                # Lógica de Filtro
                if liq >= CONFIG["min_liq"] and vol >= CONFIG["min_vol_1h"]:
                    # Verifica se não é um "scam" óbvio com 0 trades
                    if p.get('txns', {}).get('h1', {}).get('buys', 0) < 5: continue

                    print(f"🔥 ALVO IDENTIFICADO: {sym} (Liq: ${liq})")
                    ok, res = jupiter_swap(SOL, addr, CONFIG["entrada_sol"])
                    
                    if ok:
                        stats["compras"] += 1
                        alertar(f"🎯 **COMPRANDO: {sym}**\nLiquidez: ${liq}\nTX: `https://solscan.io/tx/{res['sig']}`")
                        gerenciar_saida(addr, sym, CONFIG["entrada_sol"])
                        break
                    else:
                        blacklist[addr] = time.time() + 300 # 5 min de molho se falhar rota
            
            time.sleep(4) 
        except Exception as e:
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    sniper_elite()
