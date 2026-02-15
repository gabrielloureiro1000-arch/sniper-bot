import os
import time
import threading
import json
import requests
import base58
from datetime import datetime
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

# Inicialização de APIs
bot = telebot.TeleBot(TOKEN)
solana_client = Client(RPC_URL)
app = Flask(__name__)
keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_STR))

# Memória Técnica
posicoes_abertas = {} 
historico_trades = []

# --- CONFIGURAÇÕES DE TRADE ---
CONFIG = {
    'valor_investimento_sol': 0.05, # Valor por trade (recomendo baixo para teste)
    'take_profit': 1.50,            # +50%
    'stop_loss': 0.80,              # -20%
    'max_score_risco': 500          # RugCheck Score (0-1000)
}

# --- FUNÇÕES DE SEGURANÇA E EXECUÇÃO ---

def check_seguranca(token_addr):
    """Consulta RugCheck para evitar golpes"""
    try:
        url = f"https://rugcheck.xyz/api/v1/tokens/{token_addr}/report"
        res = requests.get(url, timeout=10).json()
        score = res.get('score', 1000)
        return score <= CONFIG['max_score_risco']
    except:
        return False

def executar_swap(mint_entrada, mint_saida, amount_sol=None):
    """Executa a compra via Jupiter API v6"""
    try:
        amount = int(amount_sol * 10**9) if amount_sol else "all"
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={mint_entrada}&outputMint={mint_saida}&amount={amount}&slippageBps=150"
        quote = requests.get(quote_url).json()

        swap_payload = {
            "quoteResponse": quote,
            "userPublicKey": str(keypair.pubkey()),
            "wrapAndUnwrapSol": True
        }
        tx_res = requests.post("https://quote-api.jup.ag/v6/swap", json=swap_payload).json()

        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(tx_res['swapTransaction']))
        signature = keypair.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        
        res = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(res.value)
    except Exception as e:
        print(f"❌ Falha no Swap: {e}")
        return None

# --- LOOPS DE OPERAÇÃO ---

def loop_sniper():
    """Monitora lançamentos reais na Solana"""
    sol_mint = "So11111111111111111111111111111111111111112"
    print("🎯 Sniper ativo: Buscando tokens reais...")
    
    while True:
        try:
            # Busca tokens recém-listados via DexScreener
            resp = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10)
            tokens = resp.json()
            
            for t in tokens:
                addr = t.get('tokenAddress')
                chain = t.get('chainId')
                
                if chain == 'solana' and addr not in posicoes_abertas:
                    if check_seguranca(addr):
                        print(f"💎 Oportunidade: {addr}")
                        tx = executar_swap(sol_mint, addr, CONFIG['valor_investimento_sol'])
                        if tx:
                            posicoes_abertas[addr] = {'hora': datetime.now()}
                            bot.send_message(MY_CHAT_ID, f"🚀 **COMPRA EFETUADA!**\nToken: `{addr}`\n[Ver no Solscan](https://solscan.io/tx/{tx})", parse_mode="Markdown")
            
            time.sleep(45) # Intervalo para evitar bloqueio de IP
        except Exception as e:
            print(f"⚠️ Erro Loop: {e}")
            time.sleep(20)

def relatorio_2h():
    """Relatório periódico de saúde do bot"""
    while True:
        time.sleep(7200)
