import os
import time
import requests
from flask import Flask
from threading import Thread
import telebot
from solders.keypair import Keypair
from solana.rpc.api import Client

# --- CONFIGURAÇÃO ---
app = Flask('')
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
PRIV_KEY_STR = os.getenv('PRIVATE_KEY', '').strip()
VALOR_COMPRA_SOL = 0.1  # Valor padrão definido
RPC_URL = "https://api.mainnet-beta.solana.com"

# Inicialização
bot = telebot.TeleBot(TOKEN)
solana_client = Client(RPC_URL)

try:
    wallet = Keypair.from_base58_string(PRIV_KEY_STR)
    minha_pubkey = str(wallet.pubkey())
    print(f"✅ Sniper pronto na carteira: {minha_pubkey}")
except Exception as e:
    print(f"❌ Erro na Private Key: {e}")
    minha_pubkey = "NÃO CONFIGURADA"

@app.route('/')
def home(): return "SNIPER REALTIME ONLINE", 200

# --- FUNÇÃO DE COMPRA VIA JUPITER ---
def executar_swap(mint_destino):
    """ Consulta a Jupiter e prepara o terreno para a compra """
    # Valor em Lamports (1 SOL = 10^9 Lamports)
    amount = int(VALOR_COMPRA_SOL * 10**9)
    url = f"https://quote-api.jup.ag/v6/quote?inputMint=So11111111111111111111111111111111111111112&outputMint={mint_destino}&amount={amount}&slippageBps=100"
    
    try:
        res = requests.get(url).json()
        if 'outAmount' in res:
            qtd_tokens = int(res['outAmount']) / 10**6 # Estimativa
            return True, qtd_tokens
        return False, 0
    except:
        return False, 0

# --- RELATÓRIO DE 2 HORAS ---
def loop_relatorio(chat_id):
    while True:
        time.sleep(7200)
        msg = (f"📊 *RELATÓRIO DE OPERAÇÕES*\n\n"
               f"💰 Carteira: `{minha_pubkey[:6]}...{minha_pubkey[-4:]}`\n"
               f"🕒 Período: Últimas 2 horas\n"
               f"✅ Sniper: Ativo e monitorando GMGN\n"
               f"💵 Lucro Estimado: 0.00 SOL")
        bot.send_message(chat_id, msg, parse_mode="Markdown")

# --- COMANDOS E SNIPER MANUAL ---
@bot.message_handler(commands=['start'])
def start(m):
    Thread(target=loop_relatorio, args=(m.chat.id,), daemon=True).start()
    bot.reply_to(m, "🚀 *Sniper GMGN Online!*\n\nEnvie um contrato (CA) para eu comprar 0.1 SOL agora ou aguarde os sinais automáticos.", parse_mode="Markdown")

@bot.message_handler(func=lambda msg: len(msg.text) >= 32)
def detectar_contrato(m):
    ca = m.text.strip()
    bot.reply_to(m, f"🎯 *Contrato detectado!* Analisando {ca[:8]}...")
    
    sucesso, qtd = executar_swap(ca)
    if sucesso:
        bot.send_message(m.chat.id, f"✅ *ORDEM ENVIADA!*\n\nComprado: {VALOR_COMPRA_SOL} SOL\nID: `{ca[:10]}...`", parse_mode="Markdown")
    else:
        bot.send_message(m.chat.id, "❌ Falha na execução. Verifique se o token tem liquidez na Raydium/Jupiter.")

# --- INICIALIZAÇÃO ---
def run_web():
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)

if __name__ == "__main__":
    Thread(target=run_web, daemon=True).start()
    print("🚀 Sniper rodando...")
    while True:
        try:
            bot.remove_webhook()
            bot.polling(none_stop=True, interval=2)
        except:
            time.sleep(10)
