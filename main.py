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

# --- MODO TURBO OUSADO ---
CONFIG = {
    "entrada_sol": 0.01,
    "tp": 1.50,            # +50% Lucro
    "sl": 0.75,            # -25% Prejuízo
    "trailing_dist": 0.07, # Trailing stop de 7%
    "min_liq": 2000,       # FILTRO AGRESSIVO: Pegar tokens bem no início
    "min_vol_1h": 3000,    # Volume mínimo baixo para não perder chances
}

stats = {"compras": 0, "vendas": 0, "lucro_sol": 0.0, "erros": 0}
blacklist = {} 
start_time = time.time()

session = requests.Session()
retries = Retry(total=3, backoff_factor=0.5, status_forcelist=[429, 500])
session.mount('https://', HTTPAdapter(max_retries=retries))

@app.route('/')
def home(): return "SNIPER TURBO V4 ONLINE", 200

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

def loop_relatorio():
    while True:
        time.sleep(7200) # Relatório 2h
        relatorio = f"📈 **STATS TURBO:** {stats['compras']} compras | Lucro: {stats['lucro_sol']:.4f} SOL"
        alertar(relatorio)

def jupiter_swap(input_m, output_m, amount, slippage=2500):
    try:
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slippage}"
        quote = session.get(url, timeout=7).json()
        if "outAmount" not in quote: return False, "Sem Rota"

        data = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": 4000000 # PRIORIDADE TOTAL (0.004 SOL)
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
        time.sleep(5) # Monitoramento ultra rápido
        ok, res = jupiter_swap(addr, SOL, CONFIG["entrada_sol"]) 
        if not ok: continue
        
        p_atual = res["out"]
        lucro = p_atual / CONFIG["entrada_sol"]
        if lucro > max_p: max_p = lucro

        vender = False
        motivo = ""
        if lucro >= CONFIG["tp"]: vender, motivo = True, "TAKE PROFIT 🎯"
        elif lucro <= CONFIG["sl"]: vender, motivo = True, "STOP LOSS 🛑"
        elif lucro > 1.10 and lucro < (max_p * (1 - CONFIG["trailing_dist"])):
            vender, motivo = True, "TRAILING STOP 🛡️"

        if vender:
            v_ok, v_res = jupiter_swap(addr, SOL, CONFIG["entrada_sol"], slippage=3500)
            if v_ok:
                stats["vendas"] += 1
                stats["lucro_sol"] += (p_atual - CONFIG["entrada_sol"])
                alertar(f"💰 **VENDA TURBO: {symbol}**\nLucro: {((lucro-1)*100):.1f}% | {motivo}")
                break

def sniper_turbo():
    alertar("🚀 **MODO SNIPER TURBO V4 ATIVADO**\nFiltros reduzidos. Foco em execução imediata.")
    SOL = "So11111111111111111111111111111111111111112"
    
    while True:
        try:
            # Pega tokens com volume e novos perfis
            r = session.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=8).json()
            pairs = r.get('pairs', [])
            
            print(f"[{time.strftime('%H:%M:%S')}] Varrendo {len(pairs)} pares em modo TURBO...")

            for p in pairs:
                addr = p.get('baseToken', {}).get('address')
                sym = p.get('baseToken', {}).get('symbol')
                liq = p.get('liquidity', {}).get('usd', 0)
                vol = p.get('volume', {}).get('h1', 0)

                if addr in blacklist or p.get('chainId') != 'solana': continue

                if liq > CONFIG["min_liq"] and vol > CONFIG["min_vol_1h"]:
                    # Ignorar apenas se for um pump absurdo de 1000%
                    if float(p.get('priceChange', {}).get('h1', 0)) > 1000: continue

                    print(f"🔥 ALVO DETECTADO: {sym}")
                    ok, res = jupiter_swap(SOL, addr, CONFIG["entrada_sol"])
                    
                    if ok:
                        stats["compras"] += 1
                        alertar(f"🚀 **COMPRA TURBO: {sym}**\nTX: `https://solscan.io/tx/{res['sig']}`")
                        gerenciar_saida(addr, sym, CONFIG["entrada_sol"])
                        break
                    else:
                        blacklist[addr] = time.time() + 120 # 2 min de blacklist

            time.sleep(5) # Varredura agressiva a cada 5 segundos
        except Exception as e:
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio).start()
    sniper_turbo()
