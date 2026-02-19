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

@app.route('/')
def home():
    return "BOT SNIPER ATIVO - AGORA VAI", 200

def realizar_transacao_real(input_mint, output_mint, amount_sol):
    """ EXECUTA A COMPRA/VENDA REAL NA BLOCKCHAIN """
    try:
        amount_lamports = int(amount_sol * 1_000_000_000)
        
        # 1. Pegar a Rota
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=1500" # 15% slippage para garantir velocidade
        quote = requests.get(quote_url).json()

        if "outAmount" not in quote:
            return False, "Sem rota"

        # 2. Gerar a Transação de Swap
        swap_data = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "wrapAndUnwrapSol": True,
            "prioritizationFeeLamports": 500000 # Taxa de prioridade para ser rápido
        }
        
        tx_res = requests.post("https://quote-api.jup.ag/v6/swap", json=swap_data).json()
        tx_base64 = tx_res['swapTransaction']

        # 3. Assinar e Enviar
        raw_transaction = base64.b64decode(tx_base64)
        signature = VersionedTransaction.from_bytes(raw_transaction)
        signature = VersionedTransaction(signature.message, [carteira])
        
        res = solana_client.send_raw_transaction(bytes(signature))
        return True, res.value
    except Exception as e:
        return False, str(e)

def task_relatorio():
    while True:
        time.sleep(7200) # 2 horas
        try:
            saldo = solana_client.get_balance(carteira.pubkey()).value / 10**9
            msg = (f"📊 **RELATÓRIO OPERACIONAL**\n\n"
                   f"✅ Compras Realizadas: {stats['compras']}\n"
                   f"💰 Vendas Realizadas: {stats['vendas']}\n"
                   f"🏦 Saldo Atual: {saldo:.4f} SOL")
            bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        except: pass

def sniper_real():
    global stats
    bot.send_message(CHAT_ID, "⚡ **SNIPER REAL ATIVADO!**\nComprando 0.01 SOL em tokens novos.")
    SOL_MINT = "So11111111111111111111111111111111111111112"
    
    while True:
        try:
            # Filtro DexScreener para pegar lançamentos "quentes"
            r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1")
            if r.status_code == 200:
                tokens = r.json()
                for token in tokens[:2]: # Foca apenas nos 2 mais novos
                    addr = token.get('tokenAddress')
                    
                    # COMPRA IMEDIATA
                    sucesso, tx_id = realizar_transacao_real(SOL_MINT, addr, 0.01)
                    
                    if sucesso:
                        bot.send_message(CHAT_ID, f"🎯 **COMPRA EXECUTADA!**\nToken: `{addr}`\nTX: https://solscan.io/tx/{tx_id}")
                        stats["compras"] += 1
                        
                        # Aguarda 45 segundos para o 'pump' inicial
                        time.sleep(45)
                        
                        # VENDA IMEDIATA (Take Profit)
                        sucesso_v, tx_id_v = realizar_transacao_real(addr, SOL_MINT, 0.01)
                        if sucesso_v:
                            bot.send_message(CHAT_ID, f"💸 **VENDA EXECUTADA!**\nLucro realizado.")
                            stats["vendas"] += 1
                        break

            time.sleep(10) # Varredura agressiva
        except Exception as e:
            print(f"Erro no Loop: {e}")
            time.sleep(5)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    threading.Thread(target=task_relatorio, daemon=True).start()
    sniper_real()
