import os
import time
import threading
import requests
import base58
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# --- CONFIGURAÇÕES ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
RPC_URL = os.getenv('SOLANA_RPC_URL')
MY_CHAT_ID = os.getenv('MY_CHAT_ID') 
PRIVATE_KEY_STR = os.getenv('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
solana_client = Client(RPC_URL)
app = Flask(__name__)

COMPRA_VALOR_SOL = 0.05
TAKE_PROFIT = 1.50
STOP_LOSS = 0.80
SOL_MINT = "So11111111111111111111111111111111111111112"

historico_trades = []
posicoes_ativas = {} 

try:
    keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_STR))
    pubkey = str(keypair.pubkey())
    print(f"✅ Carteira: {pubkey}")
except Exception as e:
    print(f"❌ Erro Chave: {e}")

# --- FUNÇÃO DE SWAP (SIMPLIFICADA E CORRIGIDA) ---
def executar_swap(mint_entrada, mint_saida, amount_sol):
    # Tentamos a API principal e uma alternativa caso o DNS falhe
    urls = ["https://quote-api.jup.ag/v6", "https://jupiter-swap-api.vercel.app/v6"]
    
    for base_url in urls:
        try:
            amount_lamports = int(amount_sol * 10**9)
            # 1. Quote
            q_url = f"{base_url}/quote?inputMint={mint_entrada}&outputMint={mint_saida}&amount={amount_lamports}&slippageBps=1200"
            res_q = requests.get(q_url, timeout=10).json()
            
            if 'error' in res_q: continue

            # 2. Swap Transaction
            payload = {
                "quoteResponse": res_q,
                "userPublicKey": pubkey,
                "wrapAndUnwrapSol": True,
                "prioritizationFeeLamports": 1500000
            }
            res_s = requests.post(f"{base_url}/swap", json=payload, timeout=10).json()
            
            # 3. Assinar e Enviar
            raw_tx = VersionedTransaction.from_bytes(base58.b58decode(res_s['swapTransaction']))
            signature = keypair.sign_message(raw_tx.message)
            signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
            
            result = solana_client.send_raw_transaction(bytes(signed_tx))
            return str(result.value)
        except:
            continue
    return None

# --- FILTROS ---
def filtro_gmgn(token_addr):
    try:
        res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{token_addr}", timeout=5).json()
        pair = res.get('pairs', [{}])[0]
        liq = pair.get('liquidity', {}).get('usd', 0)
        vol = pair.get('volume', {}).get('m5', 0)
        if liq > 5000 and vol > 1000:
            return True, float(pair.get('priceUsd', 0))
    except:
        pass
    return False, 0

# --- LOOPS ---
def monitor_venda():
    while True:
        for addr, dados in list(posicoes_ativas.items()):
            try:
                res = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{addr}").json()
                price_now = float(res['pairs'][0]['priceUsd'])
                if price_now >= (dados['price_buy'] * TAKE_PROFIT) or price_now <= (dados['price_buy'] * STOP_LOSS):
                    tx = executar_swap(addr, SOL_MINT, COMPRA_VALOR_SOL)
                    if tx:
                        bot.send_message(MY_CHAT_ID, f"💰 VENDA: {addr}\nTx: {tx}")
                        del posicoes_ativas[addr]
            except: pass
        time.sleep(20)

def sniper_loop():
    while True:
        try:
            resp = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10).json()
            for t in resp:
                addr = t.get('tokenAddress')
                if t.get('chainId') == 'solana' and addr not in posicoes_ativas:
                    passou, preco = filtro_gmgn(addr)
                    if passou:
                        tx = executar_swap(SOL_MINT, addr, COMPRA_VALOR_SOL)
                        if tx:
                            posicoes_ativas[addr] = {'price_buy': preco}
                            bot.send_message(MY_CHAT_ID, f"🚀 COMPRA: {addr}\nTx: {tx}")
            time.sleep(30)
        except: time.sleep(10)

def iniciar_telegram():
    while True:
        try: bot.polling(none_stop=True)
        except: time.sleep(5)

@app.route('/')
def health(): return "ONLINE", 200

if __name__ == "__main__":
    threading.Thread(target=sniper_loop, daemon=True).start()
    threading.Thread(target=monitor_venda, daemon=True).start()
    threading.Thread(target=iniciar_telegram, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 10000)))
