import os, time, threading, requests, base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# --- CONFIG ---
TOKEN = os.environ.get('TELEGRAM_TOKEN')
CHAT_ID = os.environ.get('CHAT_ID')
RPC_URL = os.environ.get('RPC_URL')
PRIVATE_KEY = os.environ.get('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
app = Flask(__name__)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIVATE_KEY)
WSOL = "So11111111111111111111111111111111111111112"

@app.route('/')
def home(): return "EXTERMINATOR V26 - STATUS: CAÇANDO", 200

def alertar(msg):
    try: bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
    except: print(msg)

def jupiter_swap(input_m, output_m, amount, is_sell=False):
    try:
        # Slippage de 99% para compra, 20% para venda rápida
        slip = 9900 if not is_sell else 2000
        url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_m}&outputMint={output_m}&amount={int(amount*1e9)}&slippageBps={slip}"
        q = requests.get(url, timeout=5).json()
        
        payload = {
            "quoteResponse": q,
            "userPublicKey": str(carteira.pubkey()),
            "prioritizationFeeLamports": 250000000 # 0.25 SOL (Prioridade Total)
        }
        s = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        tx = VersionedTransaction.from_bytes(base64.b64decode(s['swapTransaction']))
        res = solana_client.send_raw_transaction(bytes(VersionedTransaction(tx.message, [carteira])))
        return True, str(res.value)
    except Exception as e: return False, str(e)

def monitorar_e_vender(addr, sym):
    time.sleep(45) # 45 segundos de "paciência"
    alertar(f"🔄 **TENTANDO REALIZAR LUCRO EM {sym}...**")
    for _ in range(3): # Tenta 3 vezes para não ficar preso no token
        ok, res = jupiter_swap(addr, WSOL, 0.01, is_sell=True)
        if ok:
            alertar(f"💰 **VENDA CONCLUÍDA!** Tx: `{res}`")
            return
        time.sleep(5)

def exterminator_loop():
    print("🔥 EXTERMINATOR V26 INICIADO...")
    alertar("💀 **EXTERMINATOR V26 ONLINE** - FILTROS NO CHÃO.")
    blacklist = set()
    
    while True:
        try:
            # Busca tokens em alta real
            res = requests.get("https://api.dexscreener.com/latest/dex/search?q=SOL", timeout=10)
            data = res.json()
            pairs = data.get('pairs', [])
            
            print(f"🔎 Analisando {len(pairs)} pares...")

            for pair in pairs[:40]:
                addr = pair['baseToken']['address']
                if addr in blacklist or addr == WSOL: continue
                
                # CRITÉRIO DE TIRO: Volume rápido + Liquidez mínima de $300
                m1_buys = int(pair.get('txns', {}).get('m1', {}).get('buys', 0))
                liq = float(pair.get('liquidity', {}).get('usd', 0))

                if m1_buys >= 3 and liq >= 300:
                    blacklist.add(addr)
                    alertar(f"🎯 **ALVO DETECTADO: {pair['baseToken']['symbol']}**\n💸 Liquidez: `${liq}`\n🔗 https://gmgn.ai/sol/token/{addr}")
                    
                    ok, res_tx = jupiter_swap(WSOL, addr, 0.01)
                    if ok:
                        alertar(f"✅ **TIRO CERTEIRO! COMPRADO.** Tx: `{res_tx}`")
                        threading.Thread(target=monitorar_e_vender, args=(addr, pair['baseToken']['symbol'])).start()
                        break 
        except Exception as e:
            print(f"Erro: {e}")
        
        time.sleep(2)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    exterminator_loop()
