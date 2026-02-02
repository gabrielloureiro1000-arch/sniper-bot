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

# Estratégia de Lucro
VALOR_COMPRA_SOL = 0.1
TAKE_PROFIT = 1.5  # Vende com 50% de lucro
STOP_LOSS = 0.8    # Vende com 20% de prejuízo

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
solana_client = Client(RPC_URL)

# Memória de Operações
posicoes = {}
tokens_processados = set()
lucro_sessao = 0.0
compras_sessao = 0

@app.route('/')
def health(): return "SILENT_SNIPER_RUNNING", 200

def fazer_swap(input_mint, output_mint, amount):
    try:
        payer = Keypair.from_base58_string(PRIVATE_KEY_B58)
        # Quote via Jupiter V6
        quote = requests.get(f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount)}&slippageBps=1500", timeout=10).json()
        
        # Gerar Transação
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
            "quoteResponse": quote, "userPublicKey": str(payer.pubkey()), "wrapAndUnwrapSol": True
        }, timeout=10).json()
        
        # Assinar e Enviar
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(swap_res['swapTransaction']))
        signature = payer.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        
        tx_id = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(tx_id.value), quote.get('outAmount')
    except:
        return None, None

def relatorio_horario():
    global lucro_sessao, compras_sessao
    while True:
        time.sleep(3600) # 1 hora exata
        relatorio = (
            f"📈 **RELATÓRIO DE PERFORMANCE (ÚLTIMA HORA)**\n\n"
            f"🛒 Compras realizadas: {compras_sessao}\n"
            f"💰 Lucro líquido: `{lucro_sessao:.4f} SOL`"
        )
        bot.send_message(CHAT_ID, relatorio, parse_mode="Markdown")
        # Reinicia contadores da hora
        lucro_sessao = 0.0
        compras_sessao = 0

def monitor_vendas():
    global lucro_sessao
    while True:
        for mint in list(posicoes.keys()):
            pos = posicoes[mint]
            try:
                # Checa preço atual
                res = requests.get(f"https://api.jup.ag/price/v2?ids={mint}").json()
                preco_atual = float(res['data'][mint]['price'])
                
                rendimento = preco_atual / pos['entry_price']
                
                # Gatilhos de Venda
                if rendimento >= TAKE_PROFIT or rendimento <= STOP_LOSS:
                    tx, _ = fazer_swap(mint, "So11111111111111111111111111111111111111112", pos['amount_tokens'])
                    if tx:
                        lucro_sol = (VALOR_COMPRA_SOL * rendimento) - VALOR_COMPRA_SOL
                        lucro_sessao += lucro_sol
                        tipo = "💰 LUCRO" if rendimento >= TAKE_PROFIT else "🛑 STOP LOSS"
                        bot.send_message(CHAT_ID, f"{tipo} **EXECUTADO**\n\nToken: `{mint}`\nRetorno: {rendimento:.2f}x\nTX: [Solscan](https://solscan.io/tx/{tx})")
                        del posicoes[mint]
            except: continue
        time.sleep(15)

def sniper_scanner():
    global compras_sessao
    while True:
        try:
            # Puxa os lançamentos
            data = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10).json()
            for item in data:
                addr = item.get('tokenAddress')
                
                # FILTROS RÍGIDOS (Para evitar lixo e spam):
                # 1. Deve ser Solana
                # 2. Não pode ter sido processado nesta sessão
                # 3. DEVE ter Website ou Twitter cadastrado
                has_social = any(link.get('type') in ['website', 'twitter'] for link in item.get('links', []))
                
                if item.get('chainId') == 'solana' and addr not in tokens_processados and has_social:
                    tokens_processados.add(addr)
                    
                    # TENTA A COMPRA (Em silêncio, sem avisar no Telegram antes)
                    lamports = int(VALOR_COMPRA_SOL * 1_000_000_000)
                    tx, out_amount = fazer_swap("So11111111111111111111111111111111111111112", addr, lamports)
                    
                    if tx:
                        # Se a compra funcionou, pegamos o preço de entrada e avisamos
                        try:
                            res_p = requests.get(f"https://api.jup.ag/price/v2?ids={addr}").json()
                            preco_e = float(res_p['data'][addr]['price'])
                            posicoes[addr] = {'entry_price': preco_e, 'amount_tokens': out_amount}
                            compras_sessao += 1
                            # ÚNICA MENSAGEM PERMITIDA NO SCANNER: Confirmação de Compra
                            bot.send_message(CHAT_ID, f"🛒 **COMPRA REALIZADA**\n\nToken: `{addr}`\nInvestido: 0.1 SOL\nTX: [Solscan](https://solscan.io/tx/{tx})")
                        except: continue
            
            time.sleep(30) # Delay para evitar sobrecarga e spam
        except: time.sleep(20)

if __name__ == "__main__":
    # Inicia Threads
    threading.Thread(target=sniper_scanner, daemon=True).start()
    threading.Thread(target=monitor_vendas, daemon=True).start()
    threading.Thread(target=relatorio_horario, daemon=True).start()
    # Servidor Flask para o Koyeb não derrubar o bot
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
if __name__ == "__main__":
    threading.Thread(target=sniper_scanner, daemon=True).start()
    threading.Thread(target=monitor_vendas, daemon=True).start()
    threading.Thread(target=relatorio_horario, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
