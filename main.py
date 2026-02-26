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

# --- PARÂMETROS V18 VELOCITY RIPPER ---
CONFIG = {
    "entrada_sol": 0.01,
    "min_buys_1m": 8,         # 8+ compras em apenas 60 segundos
    "velocity_trigger": 1.2,  # Entra se o preço subir 1.2% em tempo real (check-to-check)
    "take_profit": 1.15,      # Alvo de 15% de lucro
    "stop_loss": 0.93,        # Corta perda em 7%
    "priority_fee": 85000000, # Taxa Turbo (0.085 SOL) para bater os bots concorrentes
    "slippage": 4900          # 49% de margem (Garante a entrada no "vácuo" do pump)
}

stats = {"compras": 0, "vendas": 0, "lucro": 0.0, "erros": 0, "inicio": datetime.now()}
blacklist = set()
price_history = {} # Armazena o preço anterior para calcular velocidade

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: pass

@app.route('/')
def home(): return f"V18 VELOCITY RIPPER - ONLINE | Compras: {stats['compras']}", 200

def loop_relatorio():
    while True:
        time.sleep(7200) # Relatório 2h
        msg = (f"🏎️ **RELATÓRIO VELOCITY RIPPER (2H)**\n\n"
               f"🛒 Compras: `{stats['compras']}` | ✅ Vendas: `{stats['vendas']}`\n"
               f"💰 Lucro: `{stats['lucro']:.4f} SOL` | ❌ Erros: `{stats['erros']}`\n"
               f"⚡ Status: `Escaneando aceleração de preço...`")
        alertar(msg)

def jupiter_swap(input_m, output_m, amount, is_sell=False):
    try:
        slip = CONFIG["slippage"] if not is_sell else 5500
        q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slip}"
        quote = requests.get(q_url, timeout=5).json()
        if "error" in quote: return False, quote["error"]

        payload = {"quoteResponse": quote, "userPublicKey": str(carteira.pubkey()), "prioritizationFeeLamports": CONFIG["priority_fee"]}
        res = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        tx = VersionedTransaction.from_bytes(base64.b64decode(res['swapTransaction']))
        sig = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(sig.value)
    except Exception as e: return False, str(e)

def monitorar_velocidade():
    try:
        data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
        for p in data.get('pairs', []):
            addr = p['baseToken']['address']
            sym = p['baseToken']['symbol']
            if addr in blacklist or sym == "SOL": continue

            current_price = float(p.get('priceUsd', 0))
            buys_1m = int(p.get('txns', {}).get('m5', {}).get('buys', 0)) / 5 # Estimativa 1m

            # Cálculo de Velocidade (Aceleração)
            if addr in price_history:
                last_price = price_history[addr]
                velocity = (current_price / last_price) if last_price > 0 else 1
                
                # GATILHO: Aceleração detectada + Volume de compras alto
                if velocity >= (1 + (CONFIG["velocity_trigger"] / 100)) and buys_1m >= CONFIG["min_buys_1m"]:
                    blacklist.add(addr)
                    alertar(f"🚀 **ACELERAÇÃO DETECTADA: {sym}**\nVelocidade: +{velocity-1:.2%}\nCompras Est.(1m): {buys_1m:.0f}")
                    
                    ok, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                    if ok:
                        stats["compras"] += 1
                        alertar(f"✅ **COMPRA TURBO!**\nTx: `https://solscan.io/tx/{res}`")
                        threading.Thread(target=gestao_venda, args=(addr, sym)).start()
                    else:
                        stats["erros"] += 1
                        alertar(f"⚠️ **FALHA NO SNIPE:** `{res[:40]}`")
                    break

            price_history[addr] = current_price
    except Exception as e: pass

def gestao_venda(addr, sym):
    # Monitoramento agressivo de saída
    for _ in range(400): 
        try:
            q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={addr}&outputMint={WSOL}&amount={int(CONFIG['entrada_sol']*1e9)}&slippageBps=100"
            quote = requests.get(q_url, timeout=5).json()
            if "outAmount" in quote:
                atual = int(quote["outAmount"]) / 1e9
                ratio = atual / CONFIG["entrada_sol"]

                if ratio >= CONFIG["take_profit"] or ratio <= CONFIG["stop_loss"]:
                    ok, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)
                    if ok:
                        stats["vendas"] += 1
                        stats["lucro"] += (atual - CONFIG["entrada_sol"])
                        alertar(f"💰 **LUCRO NO BOLSO: {sym}**\nFator: {ratio:.2f}x")
                        return
            time.sleep(1.5) # Checa preço freneticamente
        except: time.sleep(3)
    # Venda de segurança
    jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio, daemon=True).start()
    alertar(f"🏎️ **V18 VELOCITY RIPPER ATIVADO**\nFrequência: {CONFIG['check_interval']}s | Taxa: {CONFIG['priority_fee']}")
    while True:
        monitorar_velocidade()
        time.sleep(2)
