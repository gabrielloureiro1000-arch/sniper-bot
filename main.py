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

# --- CONFIGURAÇÕES OUSADAS ---
CONFIG = {
    "entrada_sol": 0.01,
    "tp": 1.45,            # Vende com 45% de lucro
    "sl": 0.80,            # Vende se cair 20%
    "trailing_dist": 0.08, # Segue o preço com 8% de distância
    "min_liq": 4000,       # Baixei um pouco para pegar tokens mais cedo
    "min_vol_1h": 8000,
}

stats = {"compras": 0, "vendas": 0, "lucro_sol": 0.0, "erros": 0}
blacklist = {} 
start_time = time.time()

session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

@app.route('/')
def home(): return "SNIPER OUSADO V3 ATIVO", 200

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(f"TELEGRAM: {msg}")

def loop_relatorio():
    while True:
        time.sleep(7200)
        relatorio = (
            f"📊 **RELATÓRIO PRO**\n"
            f"🛒 Compras: {stats['compras']} | 💰 Lucro: {stats['lucro_sol']:.4f} SOL\n"
            f"⚠️ Erros: {stats['erros']}"
        )
        alertar(relatorio)

def jupiter_swap(input_m, output_m, amount, slippage=2000): # Slippage padrão 20%
    try:
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slippage}"
        quote = session.get(url, timeout=10).json()
        if "outAmount" not in quote: return False, "Sem Rota"

        data = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": 3000000 # Prioridade MUITO alta
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
    alertar(f"👀 Monitorando saída de **{symbol}**...")
    
    while True:
        time.sleep(10)
        ok, res = jupiter_swap(addr, SOL, CONFIG["entrada_sol"]) 
        if not ok: continue
        
        p_atual = res["out"]
        lucro = p_atual / CONFIG["entrada_sol"]
        if lucro > max_p: max_p = lucro

        vender = False
        motivo = ""
        if lucro >= CONFIG["tp"]: vender, motivo = True, "TAKE PROFIT 🎯"
        elif lucro <= CONFIG["sl"]: vender, motivo = True, "STOP LOSS 🛑"
        elif lucro > 1.15 and lucro < (max_p * (1 - CONFIG["trailing_dist"])):
            vender, motivo = True, "TRAILING STOP 🔄"

        if vender:
            v_ok, v_res = jupiter_swap(addr, SOL, CONFIG["entrada_sol"], slippage=3000)
            if v_ok:
                stats["vendas"] += 1
                stats["lucro_sol"] += (p_atual - CONFIG["entrada_sol"])
                alertar(f"💰 **VENDA: {symbol}**\nMotivo: {motivo}\nLucro: {((lucro-1)*100):.1f}%")
                break

def sniper_main():
    alertar("🎯 **SNIPER OUSADO V3 ONLINE**\nVarrendo Solana...")
    SOL = "So11111111111111111111111111111111111111112"
    
    while True:
        try:
            # Limpa blacklist antiga
            agora = time.time()
            blacklist.update({k: v for k, v in blacklist.items() if agora < v})

            # Tenta pegar os tokens com maior volume/busca
            r = session.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
            pairs = r.get('pairs', [])
            
            print(f"[{time.strftime('%H:%M:%S')}] Varrendo {len(pairs)} pares...")

            for p in pairs:
                addr = p.get('baseToken', {}).get('address')
                sym = p.get('baseToken', {}).get('symbol')
                liq = p.get('liquidity', {}).get('usd', 0)
                vol = p.get('volume', {}).get('h1', 0)

                if addr in blacklist or p.get('chainId') != 'solana': continue

                if liq > CONFIG["min_liq"] and vol > CONFIG["min_vol_1h"]:
                    # FILTRO DE ENTRADA: Não comprar se já subiu 300% em 1h
                    if float(p.get('priceChange', {}).get('h1', 0)) > 300: continue

                    print(f"🔥 Alvo Detectado: {sym} | Liq: ${liq}")
                    ok, res = jupiter_swap(SOL, addr, CONFIG["entrada_sol"])
                    
                    if ok:
                        stats["compras"] += 1
                        alertar(f"🚀 **COMPRA: {sym}**\nTX: `https://solscan.io/tx/{res['sig']}`")
                        gerenciar_saida(addr, sym, CONFIG["entrada_sol"])
                        break
                    else:
                        print(f"❌ Falha no Swap {sym}: {res}")
                        blacklist[addr] = agora + 300 # 5 min de molho

            time.sleep(20) # Varredura mais rápida
        except Exception as e:
            stats["erros"] += 1
            alertar(f"⚠️ Erro no Loop: {str(e)[:50]}")
            time.sleep(15)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio).start()
    sniper_main()
