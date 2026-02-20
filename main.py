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

# --- ESTRATÉGIA OUSADA ---
CONFIG = {
    "entrada_sol": 0.01,
    "tp": 1.40,            # Vende com 40% de lucro
    "sl": 0.82,            # Vende se cair 18% (dá espaço para o token respirar)
    "trailing_dist": 0.10, # Segue o preço com 10% de distância após bater 20% de lucro
    "min_liq": 5000,
    "min_vol_1h": 10000,
}

# --- ESTADO DO BOT ---
stats = {"compras": 0, "vendas": 0, "lucro_sol": 0.0, "erros": 0}
blacklist = {} # {address: tempo_expiracao}
start_time = time.time()

session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

@app.route('/')
def home(): return "SNIPER OUSADO OPERACIONAL", 200

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

# Relatório a cada 2 horas
def loop_relatorio():
    while True:
        time.sleep(7200)
        uptime = round((time.time() - start_time) / 3600, 1)
        relatorio = (
            f"📊 **RELATÓRIO DE PERFORMANCE**\n"
            f"⏱️ Uptime: {uptime}h\n"
            f"🛒 Compras: {stats['compras']}\n"
            f"💰 Vendas: {stats['vendas']}\n"
            f"📈 Lucro Acumulado: {stats['lucro_sol']:.4f} SOL\n"
            f"⚠️ Erros de Sistema: {stats['erros']}"
        )
        alertar(relatorio)

def jupiter_swap(input_m, output_m, amount, slippage=1500):
    try:
        quote = session.get(f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slippage}", timeout=10).json()
        if "outAmount" not in quote: return False, "Sem Liquidez"

        data = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": 2500000 
        }
        res = session.post("https://quote-api.jup.ag/v6/swap", json=data, timeout=12).json()
        
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
        time.sleep(10)
        ok, res = jupiter_swap(addr, SOL, CONFIG["entrada_sol"]) # Simula venda para ver preço
        if not ok: continue
        
        p_atual = res["out"]
        lucro = p_atual / CONFIG["entrada_sol"]
        
        if lucro > max_p: max_p = lucro

        vender = False
        motivo = ""

        if lucro >= CONFIG["tp"]:
            vender, motivo = True, "🎯 TAKE PROFIT"
        elif lucro <= CONFIG["sl"]:
            vender, motivo = True, "🛑 STOP LOSS"
        elif lucro > 1.20 and lucro < (max_p * (1 - CONFIG["trailing_dist"])):
            vender, motivo = True, "📈 TRAILING STOP"

        if vender:
            v_ok, v_res = jupiter_swap(addr, SOL, CONFIG["entrada_sol"], slippage=2500)
            if v_ok:
                stats["vendas"] += 1
                stats["lucro_sol"] += (p_atual - CONFIG["entrada_sol"])
                alertar(f"💰 **VENDA REALIZADA!**\nToken: {symbol}\nMotivo: {motivo}\nLucro: {((lucro-1)*100):.1f}%")
                break

def sniper_main():
    alertar("⚡ **SNIPER OUSADO INICIADO**\nBuscando tokens explosivos...")
    SOL = "So11111111111111111111111111111111111111112"
    
    while True:
        try:
            # Limpa blacklist
            agora = time.time()
            to_del = [k for k, v in blacklist.items() if agora > v]
            for k in to_del: del blacklist[k]

            r = session.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
            for p in r.get('pairs', []):
                addr = p.get('baseToken', {}).get('address')
                sym = p.get('baseToken', {}).get('symbol')
                liq = p.get('liquidity', {}).get('usd', 0)
                vol = p.get('volume', {}).get('h1', 0)

                if addr in blacklist or p.get('chainId') != 'solana': continue
                
                # Filtro de Volume e Liquidez
                if liq > CONFIG["min_liq"] and vol > CONFIG["min_vol_1h"]:
                    # Evita "pumps" extremos demais de 1h
                    change = float(p.get('priceChange', {}).get('h1', 0))
                    if change > 200: continue 

                    ok, res = jupiter_swap(SOL, addr, CONFIG["entrada_sol"])
                    if ok:
                        stats["compras"] += 1
                        alertar(f"🚀 **COMPRA REALIZADA!**\nToken: {sym}\nTX: `https://solscan.io/tx/{res['sig']}`")
                        gerenciar_saida(addr, sym, CONFIG["entrada_sol"])
                        break
                    else:
                        if "Liquidez" in str(res):
                            blacklist[addr] = agora + 1800 # 30 min de molho
                        else:
                            stats["erros"] += 1
                            # alertar(f"⚠️ Erro Jupiter em {sym}: {res}")

            time.sleep(30)
        except Exception as e:
            stats["erros"] += 1
            print(f"Erro Loop: {e}")
            time.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio).start()
    sniper_main()
