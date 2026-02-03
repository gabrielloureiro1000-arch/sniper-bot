import os, time, threading, requests, telebot, base58
from flask import Flask
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# === CONFIGURAÇÕES ===
TOKEN_TELEGRAM = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866"
RPC_URL = "https://api.mainnet-beta.solana.com"
PRIVATE_KEY_B58 = os.environ.get("SOLANA_PRIVATE_KEY")

VALOR_COMPRA_SOL = 0.1
TAKE_PROFIT = 1.4  # Vende com 40% de lucro (ajustado para ser mais rápido)
STOP_LOSS = 0.85   # Vende se cair 15%

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
solana_client = Client(RPC_URL)

posicoes = {}
tokens_processados = set()
lucro_total_hora = 0.0
compras_total_hora = 0

@app.route('/')
def health(): return "OK", 200

def fazer_swap(input_mint, output_mint, amount):
    try:
        payer = Keypair.from_base58_string(PRIVATE_KEY_B58)
        # Slippage alto (20%) para garantir a compra em tokens voláteis
        quote = requests.get(f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount)}&slippageBps=2000", timeout=10).json()
        
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
            "quoteResponse": quote, "userPublicKey": str(payer.pubkey()), "wrapAndUnwrapSol": True, "dynamicComputeUnitLimit": True, "prioritizationFeeLamports": 1000000
        }, timeout=10).json()
        
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(swap_res['swapTransaction']))
        signature = payer.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        tx_id = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(tx_id.value), quote.get('outAmount')
    except Exception as e:
        # Se houver erro técnico na compra, ele avisa você uma vez
        print(f"Erro Swap: {e}")
        return None, None

def relatorio_financeiro():
    global lucro_total_hora, compras_total_hora
    while True:
        time.sleep(3600)
        # Só envia relatório se houver atividade, para não poluir o chat
        if compras_total_hora > 0:
            msg = f"📊 **RESUMO DA HORA**\n\n🛒 Compras: {compras_total_hora}\n💰 Lucro: `{lucro_total_hora:.4f} SOL`"
            bot.send_message(CHAT_ID, msg, parse_mode="Markdown")
        lucro_total_hora = 0.0
        compras_total_hora = 0

def monitor_vendas():
    global lucro_total_hora
    while True:
        for mint in list(posicoes.keys()):
            pos = posicoes[mint]
            try:
                res = requests.get(f"https://api.jup.ag/price/v2?ids={mint}").json()
                preco_atual = float(res['data'][mint]['price'])
                rendimento = preco_atual / pos['entry_price']
                
                if rendimento >= TAKE_PROFIT or rendimento <= STOP_LOSS:
                    tx, _ = fazer_swap(mint, "So11111111111111111111111111111111111111112", pos['amount_tokens'])
                    if tx:
                        lucro = (VALOR_COMPRA_SOL * rendimento) - VALOR_COMPRA_SOL
                        lucro_total_hora += lucro
                        bot.send_message(CHAT_ID, f"✅ **VENDA EXECUTADA**\n\nToken: `{mint}`\nResultado: {rendimento:.2f}x\nTX: [Solscan](https://solscan.io/tx/{tx})")
                        del posicoes[mint]
            except: continue
        time.sleep(15)

def sniper_scanner():
    global compras_total_hora
    while True:
        try:
            # Pegando tokens de múltiplos filtros para aumentar chances
            data = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10).json()
            for item in data:
                addr = item.get('tokenAddress')
                
                # FILTRO RELAXADO: Agora aceita se tiver QUALQUER link ou se for de Solana recente
                if item.get('chainId') == 'solana' and addr not in tokens_processados:
                    tokens_processados.add(addr)
                    
                    # Tenta a compra (0.1 SOL)
                    lamports = int(VALOR_COMPRA_SOL * 1_000_000_000)
                    tx, out_amount = fazer_swap("So11111111111111111111111111111111111111112", addr, lamports)
                    
                    if tx:
                        time.sleep(3)
                        try:
                            res_p = requests.get(f"https://api.jup.ag/price/v2?ids={addr}").json()
                            posicoes[addr] = {'entry_price': float(res_p['data'][addr]['price']), 'amount_tokens': out_amount}
                            compras_total_hora += 1
                            bot.send_message(CHAT_ID, f"🛒 **NOVA COMPRA**\n\nToken: `{addr}`\nTX: [Solscan](https://solscan.io/tx/{tx})")
                        except: pass
            time.sleep(20) # Varre mais rápido
        except: time.sleep(10)

if __name__ == "__main__":
    threading.Thread(target=sniper_scanner, daemon=True).start()
    threading.Thread(target=monitor_vendas, daemon=True).start()
    threading.Thread(target=relatorio_financeiro, daemon=True).start()
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)))
