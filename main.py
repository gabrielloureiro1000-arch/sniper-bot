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

ENDPOINTS_JUPITER = [
    "https://quote-api.jup.ag/v6",
    "https://api.jup.ag/swap/v6"
]

session = requests.Session()
retries = Retry(total=3, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

@app.route('/')
def home():
    return "BOT SNIPER OPERACIONAL", 200

def realizar_transacao_real(input_mint, output_mint, amount_sol):
    """ Tenta executar o swap """
    amount_lamports = int(amount_sol * 1_000_000_000)
    
    for base_url in ENDPOINTS_JUPITER:
        try:
            # 1. Obter Quote
            quote_url = f"{base_url}/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=1500"
            response = session.get(quote_url, timeout=12)
            
            if response.status_code == 429:
                continue 
                
            quote = response.json()
            if "outAmount" not in quote:
                return False, "Sem liquidez"

            # 2. Gerar Swap
            swap_data = {
                "quoteResponse": quote,
                "userPublicKey": str(carteira.pubkey()),
                "wrapAndUnwrapSol": True,
                "prioritizationFeeLamports": 1500000 # Taxa de prioridade ajustada
            }
            
            tx_res = session.post(f"{base_url}/swap", json=swap_data, timeout=12).json()
            
            if 'swapTransaction' not in tx_res:
                continue

            # 3. Assinar e Enviar
            tx_base64 = tx_res['swapTransaction']
            raw_transaction = base64.b64decode(tx_base64)
            signature = VersionedTransaction.from_bytes(raw_transaction)
            signature = VersionedTransaction(signature.message, [carteira])
            
            res = solana_client.send_raw_transaction(bytes(signature))
            return True, res.value

        except Exception:
            continue

    return False, "Falha na Jupiter"

def sniper_real():
    bot.send_message(CHAT_ID, "🎯 **SNIPER ATIVO**\nBuscando tokens com liquidez...")
    SOL_MINT = "So11111111111111111111111111111111111111112"
    
    while True:
        try:
            # MUDANÇA: Buscamos tokens que já ganharam algum volume para garantir que a Jupiter os conheça
            # Usamos o endpoint de tokens com boost/tendência (Trend)
            r = session.get("https://api.dexscreener.com/token-boosts/top/v1", timeout=10)
            
            if r.status_code == 200:
                tokens = r.json()
                # Filtrar apenas tokens da rede Solana
                solana_tokens = [t for t in tokens if t.get('chainId') == 'solana']
                
                for token in solana_tokens[:3]:
                    addr = token.get('tokenAddress')
                    
                    # Tentar comprar 0.01 SOL
                    sucesso, resultado = realizar_transacao_real(SOL_MINT, addr, 0.01)
                    
                    if sucesso:
                        bot.send_message(CHAT_ID, f"🚀 **COMPRA EFETUADA!**\nToken: `{addr}`\nTX: https://solscan.io/tx/{resultado}")
                        time.sleep(45) # Espera o preço oscilar
                        
                        # Tentar vender (o bot tenta vender o que comprou)
                        venda_ok, v_res = realizar_transacao_real(addr, SOL_MINT, 0.01)
                        if venda_ok:
                            bot.send_message(CHAT_ID, f"💰 **VENDA REALIZADA!**\nTX: https://solscan.io/tx/{v_res}")
                        break
                    else:
                        print(f"Pulo: {addr[:8]}... ({resultado})")

            time.sleep(30) # Pausa entre ciclos
            
        except Exception as e:
            print(f"Erro Loop: {e}")
            time.sleep(20)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    sniper_real()
