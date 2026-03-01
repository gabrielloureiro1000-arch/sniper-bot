import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction
from datetime import datetime, timedelta

# --- CONFIGURAÇÃO DE AMBIENTE ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)
WSOL = "So11111111111111111111111111111111111111112"

# --- PARÂMETROS AGRESSIVOS ---
CONFIG = {
    "entrada_sol": 0.01,
    "min_buys_1m": 12,         # Gatilho: 12 compras no último minuto
    "min_liq_usd": 2500,       # Liquidez mínima de $2.5k
    "take_profit": 1.20,       # Alvo de 20% de lucro
    "stop_loss": 0.88,         # Stop de 12% de queda
    "priority_fee": 150000000, # 0.15 SOL (Taxa para garantir entrada)
    "slippage": 5000           # 50% de Slippage
}

# --- ESTADO DO BOT ---
stats = {
    "compras": 0,
    "vendas": 0,
    "lucro_total": 0.0,
    "erros": 0,
    "tokens_analisados": 0,
    "inicio": datetime.now()
}
blacklist = set()

def alertar(msg):
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
    except Exception as e:
        print(f"Erro Telegram: {e}")

@app.route('/')
def home():
    uptime = datetime.now() - stats["inicio"]
    return f"V24.1 ATIVA | Uptime: {uptime} | Compras: {stats['compras']} | Lucro: {stats['lucro_total']:.4f} SOL", 200

# --- RELATÓRIO DE 2 HORAS ---
def loop_relatorio():
    while True:
        time.sleep(7200) # 2 horas
        msg = (f"📊 **RELATÓRIO DE PERFORMANCE (2H)**\n"
               f"🕒 Uptime: `{datetime.now() - stats['inicio']}`\n"
               f"🔎 Tokens Analisados: `{stats['tokens_analisados']}`\n"
               f"🛒 Compras: `{stats['compras']}` | 💰 Vendas: `{stats['vendas']}`\n"
               f"💵 Lucro Estimado: `{stats['lucro_total']:.4f} SOL`\n"
               f"❌ Erros de Execução: `{stats['erros']}`")
        alertar(msg)

# --- MOTOR DE COMPRA/VENDA ---
def jupiter_swap(input_m, output_m, amount, is_sell=False):
    try:
        slip = 1000 if is_sell else CONFIG["slippage"]
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slip}"
        quote = requests.get(url, timeout=10).json()
        
        if "error" in quote: return False, f"Quote: {quote['error']}"

        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }
        res_s = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        
        tx = VersionedTransaction.from_bytes(base64.b64decode(res_s['swapTransaction']))
        sig = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(sig.value)
    except Exception as e:
        return False, str(e)

# --- GESTÃO DE SAÍDA ---
def gerenciar_saida(addr, sym, preco_entrada):
    alertar(f"⏳ **MONITORANDO VENDA: {sym}**")
    start_time = time.time()
    
    while time.time() - start_time < 900: # Max 15 min
        try:
            url = f"https://quote-api.jup.ag/v6/quote?inputMint={addr}&outputMint={WSOL}&amount={int(CONFIG['entrada_sol']*1e9)}&slippageBps=100"
            quote = requests.get(url, timeout=5).json()
            
            if "outAmount" in quote:
                atual = int(quote["outAmount"]) / 1e9
                ratio = atual / CONFIG["entrada_sol"]

                if ratio >= CONFIG["take_profit"] or ratio <= CONFIG["stop_loss"]:
                    ok, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)
                    if ok:
                        stats["vendas"] += 1
                        stats["lucro_total"] += (atual - CONFIG["entrada_sol"])
                        alertar(f"💰 **VENDA EXECUTADA: {sym}**\n📈 Resultado: `{ratio:.2f}x`\nTx: `https://solscan.io/tx/{res}`")
                        return
            time.sleep(2)
        except: time.sleep(5)
    
    # Venda forçada (Timeout)
    jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)

# --- SCANNER DE BALEIAS ---
def caçar_baleias():
    print("🚀 CAÇADA V24.1 INICIADA...")
    alertar("🌪️ **BOT STORM BREAKER ONLINE**\n*Iniciando varredura de baleias na Solana...*")
    
    while True:
        try:
            res = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=15)
            pairs = res.json().get('pairs', [])
            stats["tokens_analisados"] += len(pairs)
            
            print(f"🔎 [CHECK] {len(pairs)} tokens analisados em {datetime.now().strftime('%H:%M:%S')}")

            for pair in pairs[:40]:
                addr = pair['baseToken']['address']
                sym = pair['baseToken']['symbol']
                
                if addr in blacklist or sym == "SOL": continue
                
                m1_buys = int(pair.get('txns', {}).get('m1', {}).get('buys', 0))
                liq = float(pair.get('liquidity', {}).get('usd', 0))

                # FILTRO AGRESSIVO DE BALEIA
                if m1_buys >= CONFIG["min_buys_1m"] and liq >= CONFIG["min_liq_usd"]:
                    blacklist.add(addr)
                    gmgn = f"https://gmgn.ai/sol/token/{addr}"
                    
                    alertar(f"🐋 **BALEIA DETECTADA: {sym}**\n🔥 Compras(1m): `{m1_buys}`\n🔗 [GMGN]({gmgn})\n⚡ *COMPRANDO 0.01 SOL...*")
                    
                    ok, res_tx = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                    if ok:
                        stats["compras"] += 1
                        alertar(f"✅ **COMPRA REALIZADA!**\nTx: `https://solscan.io/tx/{res_tx}`")
                        threading.Thread(target=gerenciar_saida, args=(addr, sym, CONFIG["entrada_sol"])).start()
                    else:
                        stats["erros"] += 1
                        alertar(f"❌ **ERRO NA COMPRA {sym}:**\n`{res_tx[:60]}`")
                    break
        except Exception as e:
            print(f"Erro Loop: {e}")
        
        time.sleep(3)

if __name__ == "__main__":
    # Thread do Flask (Render)
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    # Thread do Relatório (2h)
    threading.Thread(target=loop_relatorio, daemon=True).start()
    # Loop Principal (Caçada)
    caçar_baleias()
