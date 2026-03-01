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

# --- PARÂMETROS DE GUERRA ---
CONFIG = {
    "entrada_sol": 0.01,
    "min_buys_1m": 15,         # Mínimo de 15 compras no último minuto
    "min_liq_usd": 3000,       # Liquidez mínima de $3k para conseguir sair
    "take_profit": 1.15,       # Vende com 15% de lucro
    "stop_loss": 0.90,         # Vende se cair 10%
    "priority_fee": 160000000, # 0.16 SOL (Prioridade Extrema)
    "slippage": 5000           # 50% de Slippage
}

stats = {"compras": 0, "vendas": 0, "lucro": 0.0, "inicio": datetime.now()}
blacklist = set()

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
    except: print(msg)

@app.route('/')
def home(): return f"V24 BALEIA - ATIVO | Compras: {stats['compras']} | Lucro: {stats['lucro']:.4f}", 200

def jupiter_swap(input_m, output_m, amount, is_sell=False):
    try:
        # Se for venda, usamos slippage mais baixo para garantir lucro
        slip = CONFIG["slippage"] if not is_sell else 1000
        q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slip}"
        res_q = requests.get(q_url, timeout=5).json()
        
        if "error" in res_q: return False, "Sem Liquidez/Rota"

        payload = {
            "quoteResponse": res_q,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }
        res_s = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        
        tx = VersionedTransaction.from_bytes(base64.b64decode(res_s['swapTransaction']))
        sig = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(sig.value)
    except Exception as e: return False, str(e)

def buscar_rastros_baleia():
    print("🚀 CAÇADA INICIADA...")
    while True:
        try:
            # Puxa moedas com maior volume e atividade recente
            data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
            for pair in data.get('pairs', [])[:30]:
                addr = pair['baseToken']['address']
                sym = pair['baseToken']['symbol']
                
                if addr in blacklist or sym == "SOL": continue
                
                # Análise de Volume e Pressão
                m1_buys = int(pair.get('txns', {}).get('m1', {}).get('buys', 0))
                liq = float(pair.get('liquidity', {}).get('usd', 0))
                
                # GATILHO: Muita gente comprando agora + Liquidez mínima
                if m1_buys >= CONFIG["min_buys_1m"] and liq >= CONFIG["min_liq_usd"]:
                    blacklist.add(addr)
                    gmgn = f"https://gmgn.ai/sol/token/{addr}"
                    
                    alertar(f"🐋 **BALEIA EM MOVIMENTO: {sym}**\n📈 Compras/min: `{m1_buys}`\n🔗 [Link GMGN]({gmgn})\n\n⚡ *DISPARANDO COMPRA...*")
                    
                    ok, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                    if ok:
                        stats["compras"] += 1
                        alertar(f"✅ **COMPRADO!**\nTx: `https://solscan.io/tx/{res}`")
                        # Inicia thread de venda imediata
                        threading.Thread(target=monitorar_venda, args=(addr, sym)).start()
                    else:
                        alertar(f"❌ **FALHA NO TIRO:** `{res[:50]}`")
                    break
        except: pass
        time.sleep(2)

def monitorar_venda(addr, sym):
    start_trade = time.time()
    while time.time() - start_trade < 600: # Max 10 minutos por operação
        try:
            q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={addr}&outputMint={WSOL}&amount={int(CONFIG['entrada_sol']*1e9)}&slippageBps=50"
            quote = requests.get(q_url, timeout=2).json()
            
            if "outAmount" in quote:
                atual = int(quote["outAmount"]) / 1e9
                ratio = atual / CONFIG["entrada_sol"]

                # LÓGICA DE SAÍDA AGRESSIVA
                if ratio >= CONFIG["take_profit"] or ratio <= CONFIG["stop_loss"]:
                    ok, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)
                    if ok:
                        stats["vendas"] += 1
                        stats["lucro"] += (atual - CONFIG["entrada_sol"])
                        alertar(f"💰 **VENDA FINALIZADA: {sym}**\nResultado: `{ratio:.2f}x`\nLucro: `{atual - CONFIG['entrada_sol']:.4f} SOL`")
                        return
            time.sleep(1) # Monitoramento segundo a segundo
        except: time.sleep(2)
    
    # Venda forçada por tempo
