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
        tx_res = requests.post("https://quote-api.jup.ag/v6/swap", json=swap_payload).json()

        # 3. Assinar e Enviar
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(tx_res['swapTransaction']))
        signature = keypair.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        
        res = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(res.value)
    except Exception as e:
        print(f"❌ Erro Swap: {e}")
        return None

def loop_sniper():
    """Monitora e compra tokens promissores em silêncio"""
    sol_mint = "So11111111111111111111111111111111111111112"
    print("🎯 Sniper Rodando e Analisando...")
    
    while True:
        # Simulando a captura de novos tokens da GMGN/Raydium
        # Em produção, aqui você conectaria ao stream de novos tokens
        token_alvo = "Endereço_Do_Token_Aqui" 

        if token_alvo not in posicoes_abertas:
            if check_seguranca(token_alvo):
                tx = executar_swap(sol_mint, token_alvo, CONFIG['valor_investimento_sol'])
                if tx:
                    posicoes_abertas[token_alvo] = {
                        'entrada': 1.0, # Idealmente pegar preço real da Jupiter
                        'hora': datetime.now()
                    }
                    print(f"✅ COMPRADO: {token_alvo} | TX: {tx}")
        
        time.sleep(20)

def relatorio_2h():
    """Envia o balanço de lucros a cada 2 horas"""
    while True:
        time.sleep(7200)
        if not MY_CHAT_ID: continue
        
        msg = "📊 **RELATÓRIO SNIPER (2H)**\n\n"
        if not historico_trades:
            msg += "Sem trades finalizados no período."
        else:
            total = 0
            for t in historico_trades:
                emoji = "✅" if t['lucro'] > 0 else "❌"
                msg += f"{emoji} Token `{t['token'][:5]}` | Lucro: {t['lucro']}%\n"
                total += t['lucro']
            msg += f"\n💰 **Resultado Total: {total}%**"
            historico_trades.clear()
            
        bot.send_message(MY_CHAT_ID, msg, parse_mode="Markdown")

@app.route('/')
def health(): return "ONLINE", 200

if __name__ == "__main__":
    # Inicia as engrenagens
    threading.Thread(target=loop_sniper, daemon=True).start()
    threading.Thread(target=relatorio_2h, daemon=True).start()
    
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
