import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from datetime import datetime

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

# --- PARÂMETROS DE ELITE ---
CONFIG = {
    "entrada_sol": 0.01,
    "min_volume_m5": 8000,    # Volume mínimo de $8k em 5min (Filtra lixo)
    "min_liq": 5000,          # Liquidez mínima de $5k
    "priority_fee": 120000000,# 0.12 SOL (Taxa de Predador)
    "slippage": 5000          # 50%
}

stats = {"compras": 0, "vendas": 0, "lucro": 0.0, "erros": 0}
blacklist = set()

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=False)
    except: print(msg)

@app.route('/')
def home(): return "ORACLE EYE V22 - BUSCANDO BALEIAS", 200

def loop_relatorio():
    while True:
        time.sleep(7200)
        alertar(f"📊 **RELATÓRIO PERIÓDICO**\nCompras: {stats['compras']}\nLucro Acumulado: {stats['lucro']:.4f} SOL")

def jupiter_swap(input_m, output_m, amount):
    try:
        q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={CONFIG['slippage']}"
        res_q = requests.get(q_url, timeout=5).json()
        if "error" in res_q: return False, f"Sem Rota: {res_q['error']}"

        payload = {"quoteResponse": res_q, "userPublicKey": str(carteira.pubkey()), "prioritizationFeeLamports": CONFIG["priority_fee"]}
        res_s = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        
        tx = VersionedTransaction.from_bytes(base64.b64decode(res_s['swapTransaction']))
        sig = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(sig.value)
    except Exception as e: return False, str(e)

def analisar_e_comprar():
    while True:
        try:
            # Puxa tokens com maior atividade (Boosted)
            data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
            for pair in data.get('pairs', [])[:25]:
                addr = pair['baseToken']['address']
                sym = pair['baseToken']['symbol']
                
                if addr in blacklist or sym == "SOL": continue
                
                vol_m5 = float(pair.get('volume', {}).get('m5', 0))
                liq = float(pair.get('liquidity', {}).get('usd', 0))
                m5_tx = pair.get('txns', {}).get('m5', {})
                buys = m5_tx.get('buys', 0)
                sells = m5_tx.get('sells', 0)

                # FILTRO PROMISSOR: Volume alto + Pressão de Compra + Liquidez mínima
                if vol_m5 > CONFIG["min_volume_m5"] and buys > (sells * 2) and liq > CONFIG["min_liq"]:
                    blacklist.add(addr)
                    
                    gmgn_link = f"https://gmgn.ai/sol/token/{addr}"
                    
                    alertar(f"💎 **TOKEN PROMISSOR DETECTADO!**\n\n"
                           f"📌 **Nome:** {sym}\n"
                           f"📊 **Volume (5m):** `${vol_m5:,.0f}`\n"
                           f"🔥 **Pressão:** {buys}B / {sells}S\n"
                           f"🔗 **Análise GMGN:** [CLIQUE AQUI]({gmgn_link})\n\n"
                           f"⚡ *Iniciando compra automática...*")

                    ok, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                    
                    if ok:
                        stats["compras"] += 1
                        alertar(f"✅ **COMPRA REALIZADA!**\nTx: `https://solscan.io/tx/{res}`")
                        threading.Thread(target=gestao_saida, args=(addr, sym)).start()
                    else:
                        stats["erros"] += 1
                        alertar(f"❌ **ERRO AO COMPRAR {sym}:**\n`{res[:60]}`")
                    break
        except: pass
        time.sleep(3)

def gestao_saida(addr, sym):
    # Saída inteligente: 25% de lucro ou -15% de stop
    start_time = time.time()
    while time.time() - start_time < 1200:
        try:
            q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={addr}&outputMint={WSOL}&amount={int(CONFIG['entrada_sol']*1e9)}&slippageBps=100"
            quote = requests.get(q_url, timeout=5).json()
            if "outAmount" in quote:
                atual = int(quote["outAmount"]) / 1e9
                ratio = atual / CONFIG["entrada_sol"]

                if ratio >= 1.25 or ratio <= 0.85:
                    ok, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])
                    if ok:
                        stats["vendas"] += 1
                        stats["lucro"] += (atual - CONFIG["entrada_sol"])
                        alertar(f"💰 **VENDA EXECUTADA: {sym}**\nResultado: {ratio:.2f}x\nTx: `https://solscan.io/tx/{res}`")
                        return
            time.sleep(5)
        except: pass
    # Venda de segurança
    jupiter_swap(addr, WSOL, CONFIG["entrada_sol"])

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    alertar("🚀 **ORACLE EYE V22 ATIVADO**\nConectado à GMGN.ai. Buscando lucro...")
    analisar_e_comprar()
