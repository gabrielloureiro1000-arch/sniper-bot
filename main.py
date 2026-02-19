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
    return "BOT SNIPER COM LOG DE ERROS ATIVO", 200

def realizar_transacao_real(input_mint, output_mint, amount_sol):
    """ EXECUTA A COMPRA/VENDA REAL E RETORNA O ERRO SE FALHAR """
    try:
        amount_lamports = int(amount_sol * 1_000_000_000)
        
        # 1. Pegar a Rota (Slippage em 15% para garantir execução rápida)
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount_lamports}&slippageBps=1500"
        response = requests.get(quote_url)
        quote = response.json()

        if "outAmount" not in quote:
            return False, f"Sem rota/liquidez no Jupiter para este token."

        # 2. Gerar a Transação de Swap
        swap_data = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "wrapAndUnwrapSol": True,
            "prioritizationFeeLamports": 1000000 # Taxa de prioridade (0.001 SOL) para competir
        }
        
        tx_res = requests.post("https://quote-api.jup.ag/v6/swap", json=swap_data).json()
        
        if 'swapTransaction' not in tx_res:
            return False, f"Erro na API de Swap: {tx_res.get('error', 'Erro desconhecido')}"

        tx_base64 = tx_res['swapTransaction']

        # 3. Assinar e Enviar
        raw_transaction = base64.b64decode(tx_base64)
        signature = VersionedTransaction.from_bytes(raw_transaction)
        signature = VersionedTransaction(signature.message, [carteira])
        
        res = solana_client.send_raw_transaction(bytes(signature))
        return True, res.value

    except Exception as e:
        # Captura erros de rede, saldo ou RPC
        erro_msg = str(e)
        if "insufficient funds" in erro_msg.lower():
            return False, "SALDO INSUFICIENTE (Precisa de SOL para compra + taxas)."
        return False, f"Falha técnica: {erro_msg[:100]}"

def sniper_real():
    global stats
    bot.send_message(CHAT_ID, "🚀 **SNIPER COM LOGS ATIVADO!**\nMonitorando 0.01 SOL por operação.")
    SOL_MINT = "So11111111111111111111111111111111111111112"
    
    while True:
        try:
            r = requests.get("https://api.dexscreener.com/token-profiles/latest/v1")
            if r.status_code == 200:
                tokens = r.json()
                for token in tokens[:2]:
                    addr = token.get('tokenAddress')
                    nome = token.get('symbol', 'Desconhecido')
                    
                    # TENTATIVA DE COMPRA
                    sucesso, resultado = realizar_transacao_real(SOL_MINT, addr, 0.01)
                    
                    if sucesso:
                        bot.send_message(CHAT_ID, f"✅ **COMPRA REALIZADA!**\nToken: {nome} (`{addr}`)\nTX: https://solscan.io/tx/{resultado}")
                        stats["compras"] += 1
                        time.sleep(45) # Espera o pump
                        
                        # VENDA
                        realizar_transacao_real(addr, SOL_MINT, 0.01)
                        bot.send_message(CHAT_ID, f"💰 **VENDA ENVIADA** para {nome}.")
                        break
                    else:
                        # LOG DE POR QUE NÃO COMPROU
                        print(f"Falha no token {nome}: {resultado}")
                        # Opcional: Descomente a linha abaixo para receber o motivo de cada falha no Telegram
                        # bot.send_message(CHAT_ID, f"❌ **FALHA NO TOKEN {nome}:**\n`{resultado}`")

            time.sleep(15)
        except Exception as e:
            time.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000)).start()
    sniper_real()
