import os
import time
import threading
import json
import requests
import base58
from datetime import datetime, timedelta
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# --- CONFIGURAÇÕES DE AMBIENTE ---
TOKEN = os.getenv('TELEGRAM_TOKEN')
RPC_URL = os.getenv('SOLANA_RPC_URL')
MY_CHAT_ID = os.getenv('MY_CHAT_ID') 
PRIVATE_KEY_STR = os.getenv('WALLET_PRIVATE_KEY')

# Inicialização
bot = telebot.TeleBot(TOKEN)
solana_client = Client(RPC_URL)
app = Flask(__name__)
keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_STR))

# Memória de Operações
posicoes_abertas = {} # {addr: {preco_entrada, qtd, hora}}
historico_trades = [] # Para o relatório de 2h

# --- FILTROS DE ESTRATÉGIA ---
CONFIG = {
    'valor_investimento_sol': 0.1,  # Quanto gastar por compra
    'take_profit': 1.50,            # Vender com 50% de lucro
    'stop_loss': 0.85,              # Vender se cair 15%
    'max_score_risco': 400          # Score máximo no RugCheck (quanto menor, mais seguro)
}

def check_seguranca(token_addr):
    """Verifica se o token é um golpe (Rug/Honeypot)"""
    try:
        url = f"https://rugcheck.xyz/api/v1/tokens/{token_addr}/report"
        res = requests.get(url, timeout=10).json()
        score = res.get('score', 1000)
        return score <= CONFIG['max_score_risco']
    except:
        return False

def executar_swap(mint_entrada, mint_saida, amount_sol=None):
    """Executa a troca real via Jupiter API"""
    try:
        # 1. Obter Rota
        amount = int(amount_sol * 10**9) if amount_sol else "all" # Simplificado
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={mint_entrada}&outputMint={mint_saida}&amount={amount}&slippageBps=100"
        quote = requests.get(quote_url).json()

        # 2. Criar Transação
        swap_payload = {
            "quoteResponse": quote,
            "userPublicKey": str(keypair.pubkey()),
            "wrapAndUnwrapSol": True
        }
        tx_res = requests.post("https://quote-api.jup.
