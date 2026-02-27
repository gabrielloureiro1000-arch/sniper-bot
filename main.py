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

# --- PARÂMETROS DE ATAQUE ---
CONFIG = {
    "entrada_sol": 0.01,
    "min_volume_m5": 5000,    # Volume mínimo de 5k USD em 5min
    "buy_pressure": 2.5,      # Compra deve ser 2.5x maior que a venda
    "priority_fee": 110000000,# 0.11 SOL de Taxa (Para furar qualquer fila)
    "slippage": 5500,         # 55% (Entrar no pump a qualquer custo)
}

stats = {"compras": 0, "vendas": 0, "lucro": 0.0, "erros": 0, "inicio": datetime.now()}
blacklist = set()

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

@app.route('/')
def home(): return f"LEVIATHAN V21 - ATIVO | Compras: {stats['compras']}", 200

def loop_relatorio_2h():
    while True:
        time.sleep(7200)
        msg = (f"📊 **RELATÓRIO LEVIATHAN (2H)**\n"
               f"🛒 Sucessos: `{stats['compras']}` | 💰 Lucro: `{stats['lucro']:.4f} SOL`\n"
               f"❌ Falhas: `{stats['erros']}`\n"
               f"⚡ Status: `Caçando Baleias...`")
        alertar(msg)

def jupiter_swap(input_m, output_m, amount, is_sell=False):
    try:
        slip = CONFIG["slippage"] if not is_sell else 5000
        q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slip}"
        res_q = requests.get(q_url, timeout=5).json()
        
        if "error" in res_q: return False, f"Quote Error: {res_q['error']}"

        payload = {
            "quoteResponse": res_q,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }
        res_s = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        
        tx = VersionedTransaction.from_bytes(base64.b64decode(res_s['swapTransaction']))
        sig = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(sig.value)
    except Exception as e:
        return False, str(e)

def processar_token(pair):
    try:
        addr = pair['baseToken']['address']
        sym = pair['baseToken']['symbol']
        
        if addr in blacklist or sym == "SOL": return

        # Lógica de Baleia (Pressão de Compra)
        m5 = pair.get('txns', {}).get('m5', {})
        buys = m5.get('buys', 0)
        sells = m5.get('sells', 0)
        vol = float(pair.get('volume', {}).get('m5', 0))

        if vol > CONFIG["min_volume_m5"] and buys > (sells * CONFIG["buy_pressure"]):
            blacklist.add(addr)
            alertar(f"🐋 **BALEIA DETECTADA EM {sym}**\nVolume: `${vol:,.0f}` | Buys: {buys} | Sells: {sells}")
            
            ok, res = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
            if ok:
                stats["compras"] += 1
                alertar(f"✅ **COMPRA EXECUTADA!**\nToken: {sym}\nTx: `https://solscan.io/tx/{res}`")
                threading.Thread(target=saida_estrategica, args=(addr, sym)).start()
            else:
                stats["erros"] += 1
                alertar(f"⚠️ **ERRO NA COMPRA ({sym}):**\n`{res[:100]}`")
    except: pass

def dardo_sniper():
    while True:
        try:
            # Busca os pares mais bombados da Solana no momento
            data = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10).json()
            pairs = data.get('pairs', [])[:30] # Top 30 tokens
            
            threads = []
            for p in pairs:
                t = threading.Thread(target=processar_token, args=(p,))
                threads.append(t)
                t.start()
            
            for t in threads: t.join()
        except: pass
        time.sleep(2)

def saida_estrategica(addr, sym):
    # Trailing stop: Se subir 20% e cair 5%, vende.
    pico = 0
    entrada_time = time.time()
    
    while time.time() - entrada_time < 900: # Max 15 minutos por trade
        try:
            q_url = f"https://quote-api.jup.ag/v6/quote?inputMint={addr}&outputMint={WSOL}&amount={int(CONFIG['entrada_sol']*1e9)}&slippageBps=100"
            quote = requests.get(q_url, timeout=5).json()
            if "outAmount" in quote:
                atual = int(quote["outAmount"]) / 1e9
                pico = max(pico, atual)
                
                # Se cair 10% do pico OU atingir 30% de lucro total, sai
                if atual < (pico * 0.90) or atual > (CONFIG["entrada_sol"] * 1.30):
                    ok, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)
                    if ok:
                        stats["vendas"] += 1
                        lucro_p = ((atual/CONFIG["entrada_sol"])-1)*100
                        stats["lucro"] += (atual - CONFIG["entrada_sol"])
                        alertar(f"💰 **VENDA REALIZADA: {sym}**\nLucro: `{lucro_p:.2f}%`\nTx: `https://solscan.io/tx/{res}`")
                        return
            time.sleep(3)
        except: time.sleep(5)
    
    # Venda forçada por tempo
    jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=loop_relatorio_2h, daemon=True).start()
    alertar("🐉 **LEVIATHAN V21 ATIVADO**\nAguardando o rastro das baleias...")
    dardo_sniper()
