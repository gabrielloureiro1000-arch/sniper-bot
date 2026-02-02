import os
import time
import threading
import requests
import telebot
import base58
from flask import Flask
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# === CONFIGURAÇÕES ===
TOKEN_TELEGRAM = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866"
RPC_URL = "https://api.mainnet-beta.solana.com"
PRIVATE_KEY_B58 = os.environ.get("SOLANA_PRIVATE_KEY")

# Estratégia
VALOR_COMPRA_SOL = 0.1
TAKE_PROFIT = 2.0  # 2x (100% lucro)
STOP_LOSS = 0.7    # -30% prejuízo

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
solana_client = Client(RPC_URL)

# Dicionário de posições: { 'mint': {'entry_price': 0.0, 'amount_tokens': 0} }
posicoes = {}
tokens_processados = set()

@app.route('/')
@app.route('/healthz')
def health(): return "AUTO_TRADER_V3_RUNNING", 200

def obter_preco(mint):
    try:
        res = requests.get(f"https://api.jup.ag/price/v2?ids={mint}", timeout=5).json()
        return float(res['data'][mint]['price'])
    except: return None

def fazer_swap(input_mint, output_mint, amount, is_buy=True):
    try:
        payer = Keypair.from_base58_string(PRIVATE_KEY_B58)
        # 1. Quote
        quote = requests.get(f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount)}&slippageBps=1500").json()
        
        # 2. Swap Transaction
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
            "quoteResponse": quote,
            "userPublicKey": str(payer.pubkey()),
            "wrapAndUnwrapSol": True
        }).json()
        
        # 3. Sign & Send
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(swap_res['swapTransaction']))
        signature = payer.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        
        tx_id = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(tx_id.value), quote.get('outAmount')
    except Exception as e:
        print(f"Erro Swap: {e}")
        return None, None

def monitor_vendas():
    while True:
        for mint in list(posicoes.keys()):
            pos = posicoes[mint]
            preco_atual = obter_preco(mint)
            if not preco_atual: continue
            
            rendimento = preco_atual / pos['entry_price']
            
            if rendimento >= TAKE_PROFIT or rendimento <= STOP_LOSS:
                print(f"🚨 Alvo atingido para {mint}. Vendendo...")
                tx, _ = fazer_swap(mint, "So11111111111111111111111111111111111111112", pos['amount_tokens'], is_buy=False)
                
                if tx:
                    status = "LUCRO 💰" if rendimento >= TAKE_PROFIT else "STOP 🛑"
                    bot.send_message(CHAT_ID, f"{status} **VENDA EXECUTADA**\n\nToken: `{mint}`\nResultado: {rendimento:.2f}x\nTX: [Link](https://solscan.io/tx/{tx})")
                    del posicoes[mint]
        time.sleep(15)

def sniper_scanner():
    print("🚀 Sniper Ativo: Escaneando e Comprando...")
    while True:
        try:
            data = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10).json()
            for item in data:
                addr = item.get('tokenAddress')
                if item.get('chainId') == 'solana' and addr not in tokens_processados:
                    tokens_processados.add(addr)
                    
                    # Tenta Compra
                    lamports = int(VALOR_COMPRA_SOL * 1_000_000_000)
                    tx, out_amount = fazer_swap("So11111111111111111111111111111111111111112", addr, lamports)
                    
                    if tx:
                        preco_entrada = obter_preco(addr)
                        if preco_entrada and out_amount:
                            posicoes[addr] = {'entry_price': preco_entrada, 'amount_tokens': out_amount}
                            bot.send_message(CHAT_ID, f"🛒 **COMPRA EXECUTADA**\n\nToken: `{addr}`\nPreço: ${preco_entrada}\nTX: [Solscan](https://solscan.io/tx/{tx})")
            
            time.sleep(20)
        except: time.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=sniper_scanner, daemon=True).start()
    threading.Thread(target=monitor_vendas, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
