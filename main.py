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

try:
    keypair = Keypair.from_bytes(base58.b58decode(PRIVATE_KEY_STR))
    pubkey = str(keypair.pubkey())
    print(f"✅ Carteira carregada: {pubkey}")
except Exception as e:
    print(f"❌ Erro na Private Key: {e}")

posicoes_abertas = {}

# --- FUNÇÕES DE MERCADO ---

def get_sol_balance():
    try:
        balance = solana_client.get_balance(keypair.pubkey()).value
        return balance / 10**9 # Converte Lamports para SOL
    except:
        return 0

def check_seguranca(token_addr):
    try:
        res = requests.get(f"https://rugcheck.xyz/api/v1/tokens/{token_addr}/report", timeout=5).json()
        return res.get('score', 1000) <= 500
    except:
        return False

def executar_swap(mint_entrada, mint_saida, amount_sol):
    try:
        amount_lamports = int(amount_sol * 10**9)
        quote = requests.get(f"https://quote-api.jup.ag/v6/quote?inputMint={mint_entrada}&outputMint={mint_saida}&amount={amount_lamports}&slippageBps=150", timeout=10).json()
        
        payload = {"quoteResponse": quote, "userPublicKey": pubkey, "wrapAndUnwrapSol": True}
        tx_data = requests.post("https://quote-api.jup.ag/v6/swap", json=payload, timeout=10).json()
        
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(tx_data['swapTransaction']))
        signature = keypair.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        
        res = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(res.value)
    except Exception as e:
        print(f"❌ Erro Swap: {e}")
        return None

# --- WORKERS ---

def loop_sniper():
    sol_mint = "So11111111111111111111111111111111111111112"
    while True:
        try:
            resp = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10).json()
            for t in resp:
                addr = t.get('tokenAddress')
                if t.get('chainId') == 'solana' and addr not in posicoes_abertas:
                    if check_seguranca(addr):
                        tx = executar_swap(sol_mint, addr, 0.05)
                        if tx:
                            posicoes_abertas[addr] = True
                            bot.send_message(MY_CHAT_ID, f"✅ **COMPRA!**\n`{addr}`\n[Solscan](https://solscan.io/tx/{tx})", parse_mode="Markdown")
            time.sleep(30)
        except:
            time.sleep(15)

# --- COMANDOS TELEGRAM ---

@bot.message_handler(commands=['start', 'status'])
def send_status(message):
    bot.reply_to(message, "🎯 **Sniper Online**\nBuscando novos tokens na Solana...")

@bot.message_handler(commands=['saldo'])
def send_balance(message):
    saldo = get_sol_balance()
    bot.reply_to(message, f"💰 **Saldo Atual:** {saldo:.4f} SOL\nCarteira: `{pubkey}`", parse_mode="Markdown")

# --- INICIALIZAÇÃO SEGURA ---

def iniciar_telegram():
    # Limpa Webhooks e mensagens pendentes para evitar o erro 409
    print("🧹 Limpando conexões antigas do Telegram...")
    bot.remove_webhook()
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    time.sleep(2)
    
    print("📡 Conectando modo exclusivo...")
    while True:
        try:
            bot.polling(none_stop=True, interval=1, timeout=20)
        except Exception as e:
            print(f"⚠️ Erro de Polling: {e}")
            time.sleep(5)

@app.route('/')
def health():
    return "ALIVE", 200

if __name__ == "__main__":
    # Threads de background
    threading.Thread(target=loop_sniper, daemon=True).start()
    threading.Thread(target=iniciar_telegram, daemon=True).start()
    
    # Servidor Principal
    port = int(os.environ.get("PORT", 10000))
    app.run(host='0.0.0.0', port=port)
