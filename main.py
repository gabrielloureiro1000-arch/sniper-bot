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

# --- CONFIGURAÇÃO DE ATAQUE ---
CONFIG = {
    "entrada_sol": 0.01,
    "take_profit": 1.25,      # 25% de lucro (foco em "tiros" curtos)
    "stop_loss": 0.85,        # Corta em 15% de queda
    "priority_fee": 45000000, # Reduzi para 0.045 SOL para economizar seu saldo
    "slippage": 5000,         # 50% de slippage (Essencial para tokens novos)
    "min_liq": 100            # Liquidez mínima quase zero para pegar TUDO
}

stats = {"compras": 0, "vendas": 0, "lucro": 0.0, "erros": 0, "inicio": datetime.now()}
blacklist = set()

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

@app.route('/')
def home(): return f"V19 INSTANT STRIKE - ATIVO | Compras: {stats['compras']}", 200

def jupiter_swap(input_m, output_m, amount, is_sell=False):
    try:
        q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={CONFIG['slippage']}"
        quote = requests.get(q_url, timeout=5).json()
        if "error" in quote: return False, quote["error"]

        payload = {"quoteResponse": quote, "userPublicKey": str(carteira.pubkey()), "prioritizationFeeLamports": CONFIG["priority_fee"]}
        res = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        tx = VersionedTransaction.from_bytes(base64.b64decode(res['swapTransaction']))
        sig = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(sig.value)
    except Exception as e: return False, str(e)

def caçar_tokens_novos():
    try:
        # Busca os tokens mais recentes com qualquer volume
        data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
        for p in data.get('pairs', []):
            addr = p['baseToken']['address']
            sym = p['baseToken']['symbol']
            
            if addr in blacklist or sym == "SOL": continue
            
            # Filtro de Volume: Precisa de pelo menos 10 compras nos últimos 5 min
            buys = int(p.get('txns', {}).get('m5', {}).get('buys', 0))
            liq = float(p.get('liquidity', {}).get('usd', 0))

            if buys >= 10 and liq >= CONFIG["min_liq"]:
                blacklist.add(addr)
                alertar(f"🏹 **ALVO IDENTIFICADO: {sym}**\nCompras(5m): {buys} | Liq: ${liq:,.0f}")
                
                ok, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                if ok:
                    stats["compras"] += 1
                    alertar(f"✅ **COMPRADO!**\nTx: `https://solscan.io/tx/{res}`")
                    threading.Thread(target=venda_inteligente, args=(addr, sym)).start()
                else:
                    stats["erros"] += 1
                    alertar(f"❌ **ERRO COMPRA:** `{str(res)[:40]}`")
                break
    except: pass

def venda_inteligente(addr, sym):
    # Monitora para vender em no máximo 5 minutos
    for _ in range(150):
        try:
            q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={addr}&outputMint={WSOL}&amount={int(CONFIG['entrada_sol']*1e9)}&slippageBps=100"
            quote = requests.get(q_url, timeout=5).json()
            if "outAmount" in quote:
                ratio = (int(quote["outAmount"]) / 1e9) / CONFIG["entrada_sol"]
                if ratio >= CONFIG["take_profit"] or ratio <= CONFIG["stop_loss"]:
                    ok, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)
                    if ok:
                        stats["vendas"] += 1
                        alertar(f"💰 **VENDA FINALIZADA: {sym}**\nResultado: {ratio:.2f}x")
                        return
            time.sleep(2)
        except: time.sleep(5)
    jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    alertar("⚡ **V19 INSTANT STRIKE ATIVADO**\nAgressividade total ligada.")
    while True:
        caçar_tokens_novos()
        time.sleep(2)
