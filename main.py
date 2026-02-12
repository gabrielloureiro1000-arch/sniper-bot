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

# --- CONFIGURAÇÕES FIXAS ---
VALOR_COMPRA_SOL = 0.1
SLIPPAGE_BPS = 3000
PRIORITY_FEE = 150000
TAKE_PROFIT = 2.0
STOP_LOSS = 0.85

app = Flask('')
TOKEN = os.getenv('TELEGRAM_TOKEN', '').strip()
PRIV_KEY = os.getenv('PRIVATE_KEY', '').strip()
RPC_URL = os.getenv('RPC_URL', '').strip()

bot = telebot.TeleBot(TOKEN)
solana_client = Client(RPC_URL)
carteira = Keypair.from_base58_string(PRIV_KEY)
chat_id_dono = None

stats = {"analisadas": 0, "compradas": 0, "vendidas": 0, "lucro_sol": 0.0, "rugpulls_evitados": 0}
trades_ativos = {}

def executar_swap(input_mint, output_mint, amount, motivo="COMPRA"):
    # BLOQUEIO DE SEGURANÇA: Nunca tenta comprar o endereço de exemplo dos logs
    if "Endereço" in output_mint or "Token" in output_mint or len(output_mint) < 30:
        return None, None
    
    try:
        # Tenta conectar na Jupiter V6
        quote_res = requests.get(f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={amount}&slippageBps={SLIPPAGE_BPS}", timeout=10)
        quote = quote_res.json()
        
        if 'outAmount' not in quote: return None, None
        
        payload = {
            "quoteResponse": quote,
            "userPublicKey": str(carteira.pubkey()),
            "wrapAndUnwrapSol": True,
            "computeUnitPriceMicroLamports": PRIORITY_FEE
        }
        
        tx_res = requests.post("https://quote-api.jup.ag/v6/swap", json=payload, timeout=10).json()
        raw_tx = base64.b64decode(tx_res['swapTransaction'])
        transaction = VersionedTransaction.from_bytes(raw_tx)
        signature = carteira.sign_message(transaction.message)
        transaction.signatures = [signature]
        
        # Envia via Helius
        solana_client.send_raw_transaction(bytes(transaction))
        return quote['outAmount'], float(quote['swapUsdValue'])
    except Exception as e:
        print(f"Erro na execução: {e}")
        return None, None

def gerar_relatorio():
    taxa = (stats["vendidas"] / stats["compradas"] * 100) if stats["compradas"] > 0 else 0
    return (
        f"📊 *RELATÓRIO ELITE*\n"
        f"💰 Lucro: {stats['lucro_sol']:.4f} SOL\n"
        f"🎯 Compras: {stats['compradas']}\n"
        f"🛡️ Rugpulls Evitados: {stats['rugpulls_evitados']}\n"
        f"📈 Taxa: {taxa:.1f}%"
    )

@bot.message_handler(commands=['start'])
def start(m):
    global chat_id_dono
    chat_id_dono = m.chat.id
    bot.reply_to(m, "🎯 *SNIPER ONLINE!* Monitorando DexScreener...")

@app.route('/')
def home():
    return gerar_relatorio(), 200

def buscar_gemas():
    print("🛰️ Scanner iniciado...")
    while True:
        try:
            # Pega sinais reais da DexScreener
            res = requests.get("https://api.dexscreener.com/token-boosts/latest/v1", timeout=10).json()
            for gema in res[:5]:
                stats["analisadas"] += 1
                mint = gema['tokenAddress']
                
                if mint not in trades_ativos:
                    # Tenta a compra real
                    lamports = int(VALOR_COMPRA_SOL * 10**9)
                    out, usd = executar_swap("So11111111111111111111111111111111111111112", mint, lamports)
                    
                    if out:
                        stats["compradas"] += 1
                        trades_ativos[mint] = True
                        if chat_id_dono:
                            bot.send_message(chat_id_dono, f"🚀 *COMPRA:* `{mint}`")
            time.sleep(40)
        except Exception as e:
            print(f"Erro Scanner: {e}")
            time.sleep(15)

if __name__ == "__main__":
    # Roda o Flask em thread separada
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=10000), daemon=True).start()
    # Roda o Scanner
    threading.Thread(target=buscar_gemas, daemon=True).start()
    # Roda o Bot (usando non-stop para evitar quedas)
    print("🤖 Bot em polling...")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
