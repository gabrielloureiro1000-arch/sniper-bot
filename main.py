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

# --- CONFIGURAÇÕES DO SISTEMA ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
RPC_URL = os.getenv('SOLANA_RPC_URL')
MY_CHAT_ID = os.getenv('MY_CHAT_ID') 
PRIVATE_KEY_STR = os.getenv('WALLET_PRIVATE_KEY')

bot = telebot.TeleBot(TOKEN)
solana_client = Client(RPC_URL)
app = Flask(__name__)

# Configurações de Estratégia
COMPRA_VALOR_SOL = 0.05
TAKE_PROFIT = 1.50  # Vende com 50% de lucro
STOP_LOSS = 0.80    # Vende se cair 20%
SOL_MINT = "So11111111111111111111111111111111111111112"

# Memória do Bot
historico_trades = []
posicoes_ativas = {} 

try:
    keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_STR))
    pubkey = str(keypair.pubkey())
    print(f"✅ Carteira carregada: {pubkey}")
except Exception as e:
    print(f"❌ Erro na Chave Privada: {e}")

# --- FUNÇÃO DE COMPRA/VENDA BLINDADA ---

def executar_swap(mint_entrada, mint_saida, amount_sol):
    # Lista de caminhos alternativos para não dar erro de conexão
    endpoints = [
        "https://quote-api.jup.ag/v6",
        "https://jupiter-swap-api.vercel.app/v6"
    ]
    
    for api_url in endpoints:
        try:
            # Converte valor para o formato da rede
            amount = int(amount_sol * 10**9)
            
            # 1. Pede o melhor preço (Slippage 12% para entrar rápido)
            quote_res = requests.get(
                f"{api_url}/quote?inputMint={mint_entrada}&outputMint={mint_saida}&amount={amount}&slippageBps=1200",
                timeout=15
            ).json()

            if 'error' in quote_res:
                continue

            # 2. Prepara o pacote da transação
            payload = {
                "quoteResponse": quote_res,
                "userPublicKey": pubkey,
                "wrapAndUnwrapSol": True,
                "prioritizationFeeLamports": 1500000 # Taxa de prioridade alta
            }
            
            tx_data = requests.post(f"{api_url}/swap", json=payload, timeout=15).json()
            
            # 3. Assina o "cheque" digital com sua chave
            raw_tx = VersionedTransaction.from_bytes(base58.b58decode(tx_data['swapTransaction']))
            signature = keypair.sign_message(raw_tx.message)
            signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
            
            # 4. Envia para a rede Solana
            result = solana_client.send_raw_transaction(bytes(signed_tx))
            return str
