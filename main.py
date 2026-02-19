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

stats = {"compras": 0, "vendas": 0, "lucro_sol": 0.0}

# Configuração de Sessão Anti-Bloqueio
session = requests.Session()
retries = Retry(total=5, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
session.mount('https://', HTTPAdapter(max_retries=retries))

@app.route('/')
def home():
    return "BOT SNIPER ANTI-BLOQUEIO ATIVO", 200

def realizar_transacao_real(input_mint, output_mint, amount_sol):
    """ EXECUTA A COMPRA/VENDA REAL COM TRATAMENTO DE CONEXÃO """
    try:
        amount_lamports = int(amount_sol * 1_000_000_000)
        
        # 1. Pegar a Rota com Timeout
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=1500"
        response = session.get(quote_url, timeout=15)
        quote = response.json()

        if "outAmount" not in quote:
            return False, "Token sem liquidez ou rota no Jupiter."

        # 2. Gerar a Transação de Swap
        swap_data = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "wrapAndUnwrapSol": True,
            "prioritizationFeeLamports": 1000000 
        }
        
        tx_res = session.post("https://quote-api.jup.ag/v6/swap", json=swap_data, timeout=15).json()
        
        if 'swapTransaction' not in tx_res:
            return False, f"Erro Jupiter: {tx_res.get('error', 'Sem transação disponível')}"

        tx_base64 = tx_res['swapTransaction']

        # 3. Assinar e Enviar
        raw_transaction = base64.b64decode(tx_base64)
        signature = VersionedTransaction.from_bytes(raw_transaction)
        signature = VersionedTransaction(signature.message, [carteira])
        
        res = solana_client.send_raw_transaction(bytes(signature))
        return True, res.value

    except requests.exceptions.ConnectionError:
        return False, "BLOQUEIO DE IP: A Jupiter limitou o Render. Aguardando pausa..."
    except Exception as e:
        erro_msg = str(e)
        if "insufficient funds" in erro_msg.lower():
            return False, "SALDO INSUFICIENTE para compra + taxas."
        return False, f"Falha técnica: {erro_msg[:50]}"

def sniper_real():
    global stats
    bot.send_message(CHAT_ID, "🚀 **SNIPER ANTI-BLOQUEIO INICIADO!**\nAlvo: 0.01 SOL por trade.")
    SOL_MINT = "So11111111111111111111111111111111111111112"
    
    while True:
        try:
            # Busca tokens recentes
            r = session.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10)
            if r.status_code == 200:
                tokens = r.json()
                for token in tokens[:2]:
                    addr = token.get('tokenAddress')
                    nome = token.get('symbol', '???')
                    
                    # TENTATIVA DE COMPRA
                    sucesso, resultado = realizar_transacao_real(SOL_MINT, addr, 0.01)
                    
                    if sucesso:
                        bot.send_message(CHAT_ID, f"✅ **COMPRA EXECUTADA!**\nToken: {nome}\nTX: https://solscan.io/tx/{resultado}")
                        stats["compras"] += 1
                        time.sleep(60) # Espera 1 minuto para maturação
                        
                        # VENDA
                        venda_ok, v_res = realizar_transacao_real(addr, SOL_MINT, 0.01)
                        if venda_ok:
                            bot.send_message(CHAT_ID, f"💰 **VENDA REALIZADA** de {nome}.")
                            stats["vendas"] += 1
                        break
                    else:
                        # Log no console do Render para você monitorar
                        print(f"Pulo no token {nome}: {resultado}")

            # Pausa de 30 segundos para evitar banimento de IP (Rate Limit)
            time.sleep(30)
            
        except Exception as e:
            print(f"Erro no Loop: {e}")
            time.sleep(20)

if __name__ == "__main__":
    # Flask em thread separada para o Render não derrubar o serviço
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    sniper_real()
