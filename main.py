import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

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

# --- CONFIGURAÇÃO KRAKEN ---
CONFIG = {
    "entrada_sol": 0.01,
    "min_liq_usd": 100,        
    "priority_fee": 250000000, # 0.25 SOL (Taxa de Sniper)
    "slippage": 9900           
}

def alertar(msg):
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
    except:
        print(f"Erro Telegram: {msg}")

@app.route('/')
def home():
    return "🐙 KRAKEN V27.1 ATIVA - VARRENDO SOLANA", 200

# --- MOTOR DE EXECUÇÃO JUPITER V6 ---
def jupiter_swap(input_m, output_m, amount, is_sell=False):
    try:
        slip = 2500 if is_sell else CONFIG["slippage"]
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slip}"
        quote = requests.get(url, timeout=10).json() # Timeout maior para evitar o erro de resolução
        
        if "error" in quote: return False, f"Quote: {quote['error']}"

        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": CONFIG["priority_fee"]
        }
        res_s = requests.post("https://quote-api.jup.ag/v6/swap", json=payload, timeout=10).json()
        
        tx = VersionedTransaction.from_bytes(base64.b64decode(res_s['swapTransaction']))
        sig = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(sig.value)
    except Exception as e:
        return False, str(e)

# --- SAÍDA RELÂMPAGO (45 SEGUNDOS) ---
def monitorar_e_vender(addr, sym):
    time.sleep(45)
    alertar(f"🔄 **KRAKEN TENTANDO REALIZAR LUCRO EM {sym}...**")
    
    for tentativa in range(3):
        ok, res = jupiter_swap(addr, WSOL, CONFIG["entrada_sol"], is_sell=True)
        if ok:
            alertar(f"💰 **VENDA CONCLUÍDA!**\nTx: `https://solscan.io/tx/{res}`")
            return
        time.sleep(5)
    alertar(f"⚠️ **FALHA AO VENDER {sym}**")

# --- LOOP KRAKEN: VARREDURA TOTAL ---
def exterminator_loop():
    print("🐙 MODO KRAKEN INICIADO - PESCANDO LANÇAMENTOS...")
    alertar("🐙 **MODO KRAKEN V27.1 ONLINE**")
    blacklist = set()
    
    while True:
        try:
            res = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=8)
            data = res.json()
            pairs = data.get('pairs', [])
            
            print(f"🔎 [KRAKEN] Analisando {len(pairs)} pares ativos...")

            for pair in pairs[:100]:
                addr = pair['baseToken']['address']
                
                # --- FILTRO LIMPO ---
                # Ignora o que já compramos, ignora SOL e ignora endereços de outras redes (0x)
                if addr in blacklist or addr == WSOL or addr.startswith("0x"): 
                    continue
                
                liq = float(pair.get('liquidity', {}).get('usd', 0))
                
                if liq >= CONFIG["min_liq_usd"]:
                    blacklist.add(addr)
                    sym = pair['baseToken']['symbol']
                    
                    alertar(f"🚨 **ALVO DETECTADO: {sym}**\nLiquidez: `${liq}`\n🔗 [GMGN](https://gmgn.ai/sol/token/{addr})")
                    
                    try:
                        ok, res_tx = jupiter_swap(WSOL, addr, CONFIG["entrada_sol"])
                        if ok:
                            alertar(f"✅ **TIRO CERTEIRO! COMPRADO.**\nToken: {sym}\nTx: `https://solscan.io/tx/{res_tx}`")
                            threading.Thread(target=monitorar_e_vender, args=(addr, sym)).start()
                            break 
                        else:
                            print(f"Falha na compra de {sym}: {res_tx}")
                    except Exception as swap_err:
                        print(f"Erro de conexão Jupiter: {swap_err}")
                        
        except Exception as e:
            print(f"Erro no Loop: {e}")
        
        time.sleep(2) # Intervalo seguro para evitar bloqueio de IP

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    exterminator_loop()
