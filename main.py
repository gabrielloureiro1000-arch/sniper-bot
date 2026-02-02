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

# Metas de Venda
TAKE_PROFIT = 2.0  # Vende quando dobrar (2x)
STOP_LOSS = 0.7    # Vende se cair 30% (0.7 do valor original)

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
solana_client = Client(RPC_URL)

# Dicionário para gerenciar o que foi comprado: { 'token_address': { 'entry_price': 0.0, 'amount': 0 } }
posicoes_abertas = {}

@app.route('/')
def health(): return "AUTO_TRADER_V2_ACTIVE", 200

def obter_preco(mint):
    try:
        url = f"https://api.jup.ag/price/v2?ids={mint}"
        res = requests.get(url).json()
        return float(res['data'][mint]['price'])
    except: return None

def executar_swap(input_mint, output_mint, amount_lamports):
    """Função genérica para Swap (Compra ou Venda)"""
    try:
        payer = Keypair.from_base58_string(PRIVATE_KEY_B58)
        quote_url = f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount_lamports)}&slippageBps=1500"
        quote = requests.get(quote_url).json()
        
        swap_data = {"quoteResponse": quote, "userPublicKey": str(payer.pubkey()), "wrapAndUnwrapSol": True}
        tx_res = requests.post("https://quote-api.jup.ag/v6/swap", json=swap_data).json()
        
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(tx_res['swapTransaction']))
        signature = payer.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        
        result = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(result.value)
    except Exception as e:
        print(f"Erro no Swap: {e}")
        return None

def monitor_de_vendas():
    """Loop que vigia as moedas compradas para vender no lucro/prejuízo"""
    print("📈 Monitor de Vendas iniciado...")
    while True:
        for mint, info in list(posicoes_abertas.items()):
            preco_atual = obter_preco(mint)
            if not preco_atual: continue
            
            lucro = preco_atual / info['entry_price']
            
            if lucro >= TAKE_PROFIT or lucro <= STOP_LOSS:
                print(f"🚀 Alvo atingido para {mint}. Vendendo...")
                # Lógica simplificada: Venda exige saber o saldo exato (tokens). 
                # Para simplificar este código, o bot avisa e tenta vender o que comprou.
                tx = executar_swap(mint, "So11111111111111111111111111111111111111112", info['amount_tokens'])
                
                status = "LUCRO 🚀" if lucro >= TAKE_PROFIT else "STOP LOSS 🛑"
                if tx:
                    bot.send_message(CHAT_ID, f"✅ **VENDA EXECUTADA ({status})**\nToken: `{mint}`\nRetorno: {lucro:.2f}x")
                    del posicoes_abertas[mint]
        time.sleep(10)

def sniper_loop():
    print("🚀 Sniper e Comprador iniciado...")
    while True:
        try:
            url = "https://api.dexscreener.com/token-profiles/latest/v1"
            tokens = requests.get(url).json()
            for t in tokens:
                addr = t.get('tokenAddress')
                if t.get('chainId') == 'solana' and addr not in posicoes_abertas:
                    # COMPRA
                    print(f"🎯 Comprando novo token: {addr}")
                    tx = executar_swap("So11111111111111111111111111111111111111112", addr, 100_000_000) # 0.1 SOL
                    
                    if tx:
                        preco = obter_preco(addr)
                        if preco:
                            posicoes_abertas[addr] = {'entry_price': preco, 'amount_tokens': 1000000} # Exemplo simplificado de amount
                            bot.send_message(CHAT_ID, f"🛒 **COMPRA AUTOMÁTICA**\nToken: `{addr}`\nTX: {tx}")
            time.sleep(20)
        except: time.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=sniper_loop, daemon=True).start()
    threading.Thread(target=monitor_de_vendas, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
