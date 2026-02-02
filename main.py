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
TAKE_PROFIT = 1.5  # Vende com 50% de lucro
STOP_LOSS = 0.8    # Vende com 20% de prejuízo

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
solana_client = Client(RPC_URL)

# Banco de dados temporário
posicoes = {}
tokens_processados = set()
lucro_acumulado = 0.0
total_compras = 0

@app.route('/')
def health(): return "SNIPER_SILENCIOSO_ATIVO", 200

def obter_preco(mint):
    try:
        res = requests.get(f"https://api.jup.ag/price/v2?ids={mint}", timeout=5).json()
        return float(res['data'][mint]['price'])
    except: return None

def fazer_swap(input_mint, output_mint, amount):
    try:
        payer = Keypair.from_base58_string(PRIVATE_KEY_B58)
        quote = requests.get(f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount)}&slippageBps=1500").json()
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
            "quoteResponse": quote, "userPublicKey": str(payer.pubkey()), "wrapAndUnwrapSol": True
        }).json()
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(swap_res['swapTransaction']))
        signature = payer.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        tx_id = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(tx_id.value), quote.get('outAmount')
    except: return None, None

def relatorio_horario():
    global lucro_acumulado, total_compras
    while True:
        time.sleep(3600) # 1 hora
        msg = (
            f"📊 **RELATÓRIO DE PERFORMANCE (ÚLTIMA HORA)**\n\n"
            f"🛒 Compras realizadas: {total_compras}\n"
            f"💰 Lucro/Prejuízo: `{lucro_acumulado:.4f} SOL`"
        )
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        # Zera para a próxima hora se preferir, ou mantém acumulado
        total_compras = 0
        lucro_acumulado = 0.0

def monitor_vendas():
    global lucro_acumulado
    while True:
        for mint in list(posicoes.keys()):
            pos = posicoes[mint]
            preco_atual = obter_preco(mint)
            if not preco_atual: continue
            
            rendimento = preco_atual / pos['entry_price']
            if rendimento >= TAKE_PROFIT or rendimento <= STOP_LOSS:
                tx, _ = fazer_swap(mint, "So11111111111111111111111111111111111111112", pos['amount_tokens'])
                if tx:
                    resultado_sol = (VALOR_COMPRA_SOL * rendimento) - VALOR_COMPRA_SOL
                    lucro_acumulado += resultado_sol
                    status = "✅ VENDA NO LUCRO" if rendimento >= TAKE_PROFIT else "🛑 STOP LOSS"
                    bot.send_message(CHAT_ID, f"{status}\nToken: `{mint}`\nResultado: {rendimento:.2f}x\nTX: [Solscan](https://solscan.io/tx/{tx})")
                    del posicoes[mint]
        time.sleep(10)

def sniper_scanner():
    global total_compras
    print("🎯 Sniper Silencioso rodando filtros de elite...")
    while True:
        try:
            data = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10).json()
            for item in data:
                addr = item.get('tokenAddress')
                # FILTROS DE ELITE: Solana + Não repetido + Tem que ter Website ou Twitter
                tem_social = any(link.get('type') in ['website', 'twitter'] for link in item.get('links', []))
                
                if item.get('chainId') == 'solana' and addr not in tokens_processados and tem_social:
                    tokens_processados.add(addr)
                    
                    # Tenta Compra
                    lamports = int(VALOR_COMPRA_SOL * 1_000_000_000)
                    tx, out_amount = fazer_swap("So11111111111111111111111111111111111111112", addr, lamports)
                    
                    if tx:
                        preco_entrada = obter_preco(addr)
                        if preco_entrada and out_amount:
                            posicoes[addr] = {'entry_price': preco_entrada, 'amount_tokens': out_amount}
                            total_compras += 1
                            bot.send_message(CHAT_ID, f"🛒 **COMPRA EXECUTADA**\nToken: `{addr}`\nTX: [Solscan](https://solscan.io/tx/{tx})")
            time.sleep(30)
        except: time.sleep(20)

if __name__ == "__main__":
    threading.Thread(target=sniper_scanner, daemon=True).start()
    threading.Thread(target=monitor_vendas, daemon=True).start()
    threading.Thread(target=relatorio_horario, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
