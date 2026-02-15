import os
import time
import threading
import requests
import base58
from datetime import datetime
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

# Tenta carregar a chave, se falhar o bot avisa no log
try:
    keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_STR))
    print(f"✅ Carteira carregada: {keypair.pubkey()}")
except Exception as e:
    print(f"❌ Erro na Private Key: {e}")

posicoes_abertas = {}

# --- FUNÇÕES TÉCNICAS ---

def check_seguranca(token_addr):
    try:
        res = requests.get(f"https://rugcheck.xyz/api/v1/tokens/{token_addr}/report", timeout=5).json()
        return res.get('score', 1000) <= 500
    except:
        return False

def executar_swap(mint_entrada, mint_saida, amount_sol):
    try:
        amount_lamports = int(amount_sol * 10**9)
        quote = requests.get(f"https://quote-api.jup.ag/v6/quote?inputMint={mint_entrada}&outputMint={mint_saida}&amount={amount_lamports}&slippageBps=100").json()
        
        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(keypair.pubkey()),
            "wrapAndUnwrapSol": True
        }
        tx_data = requests.post("https://quote-api.jup.ag/v6/swap", json=payload).json()
        
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(tx_data['swapTransaction']))
        signature = keypair.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        
        res = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(res.value)
    except Exception as e:
        print(f"❌ Erro Swap: {e}")
        return None

# --- WORKERS (THREADS) ---

def loop_sniper():
    print("🎯 Sniper iniciado em segundo plano...")
    sol_mint = "So11111111111111111111111111111111111111112"
    while True:
        try:
            # Monitora tokens recentes via DexScreener
            resp = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10).json()
            for t in resp:
                addr = t.get('tokenAddress')
                if t.get('chainId') == 'solana' and addr not in posicoes_abertas:
                    if check_seguranca(addr):
                        tx = executar_swap(sol_mint, addr, 0.05) # Compra 0.05 SOL
                        if tx:
                            posicoes_abertas[addr] = True
                            bot.send_message(MY_CHAT_ID, f"✅ **COMPRA!**\n`{addr}`\n[Solscan](https://solscan.io/tx/{tx})", parse_mode="Markdown")
            time.sleep(30)
        except Exception as e:
            print(f"⚠️ Erro Sniper: {e}")
            time.sleep(10)

def relatorio_2h():
    while True:
        time.sleep(7200)
        try:
            bot.send_message(MY_CHAT_ID, "📊 **Bot Ativo**\nMonitorando novas listagens na Solana.")
        except: pass

# --- COMANDOS TELEGRAM ---

@bot.message_handler(commands=['start', 'status'])
def send_welcome(message):
    bot.reply_to(message, "🚀 **Sniper Online!**\nUse /status para checar o funcionamento.")

# --- INICIALIZAÇÃO ---

@app.route('/')
def home():
    return "SERVER_OK", 200

def run_bot():
    # Esta função inicia as threads secundárias
    threading.Thread(target=loop_sniper, daemon=True).start()
    threading.Thread(target=relatorio_2h, daemon=True).start()
    threading.Thread(target=bot.infinity_polling, daemon=True).start()

if __name__ == "__main__":
    # Primeiro: dispara o bot em threads
    run_bot()
    
    # Segundo: Trava no Flask para o Render não fechar
    port = int(os.environ.get("PORT", 10000))
    print(f"🌍 Servidor Web na porta {port}")
    app.run(host='0.0.0.0', port=port)
