import os
import time
import requests
import threading
import base64
from flask import Flask
import telebot
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# Configurações
VALOR_COMPRA_SOL = 0.1
SLIPPAGE_BPS = 3000

app = Flask('')
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
PRIV_KEY = os.getenv('PRIVATE_KEY', '').strip()
RPC_URL = os.getenv('RPC_URL', '').strip()

bot = telebot.TeleBot(TOKEN)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIV_KEY)

stats = {"analisadas": 0, "compradas": 0}

def executar_swap(input_mint, output_mint, amount):
    # Proteção contra endereços inválidos dos logs anteriores
    if "Endereço" in output_mint or len(output_mint) < 30:
        return None
    
    url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount}&slippageBps={SLIPPAGE_BPS}"
    
    for _ in range(3): # Tenta 3 vezes em caso de erro de DNS
        try:
            response = requests.get(url, timeout=15)
            quote = response.json()
            if 'outAmount' in quote:
                return quote['outAmount']
        except Exception as e:
            print(f"⚠️ Tentativa de conexão falhou (DNS/Rede). Tentando novamente...")
            time.sleep(2)
    return None

@app.route('/')
def home():
    return f"Sniper Ativo - Analisadas: {stats['analisadas']}", 200

def buscar_gemas():
    print("🛰️ Scanner iniciado...")
    while True:
        try:
            # Pegando tokens reais da DexScreener
            res = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=10).json()
            for gema in res[:3]:
                stats["analisadas"] += 1
                mint = gema['tokenAddress']
                
                # Tenta cotar o swap
                out = executar_swap("So11111111111111111111111111111111111111112", mint, int(VALOR_COMPRA_SOL * 10**9))
                if out:
                    print(f"✅ Token válido encontrado: {mint}")
                    stats["compradas"] += 1
            
            time.sleep(30)
        except Exception as e:
            print(f"Erro no loop principal: {e}")
            time.sleep(10)

if __name__ == "__main__":
    # Inicia Flask
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    # Inicia Scanner
    threading.Thread(target=buscar_gemas, daemon=True).start()
    
    # Inicia Bot Telegram com tratamento de erro 409
    print("🤖 Bot conectando ao Telegram...")
    while True:
        try:
            bot.polling(none_stop=True, interval=3, timeout=20)
        except Exception as e:
            print(f"Erro no Polling (Pode ser o 409): {e}")
            time.sleep(10) # Espera a outra instância morrer no Render
