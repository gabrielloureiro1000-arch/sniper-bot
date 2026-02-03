import os, time, threading, requests, telebot, base58
from flask import Flask
from solana.rpc.api import Client
from solders.keypair import Keypair
from solders.transaction import VersionedTransaction

# === CONFIGURAÇÕES ===
TOKEN_TELEGRAM = "8595782081:AAGX0zuwjeZtccuMBWXNIzW-VmLuPMmH1VI"
CHAT_ID = "5080696866"
RPC_URL = "https://api.mainnet-beta.solana.com"
# Busca a chave, se não achar, usa uma string vazia para não travar o código
PRIVATE_KEY_B58 = os.environ.get("SOLANA_PRIVATE_KEY", "")

bot = telebot.TeleBot(TOKEN_TELEGRAM)
app = Flask(__name__)
solana_client = Client(RPC_URL)

# --- SERVIDOR PARA O KOYEB NÃO DAR ERRO ---
@app.route('/')
@app.route('/healthz')
def health():
    return "ALIVE", 200

# --- FUNÇÃO DE COMPRA/VENDA ---
def fazer_swap(input_mint, output_mint, amount):
    if not PRIVATE_KEY_B58:
        print("ERRO: Variável SOLANA_PRIVATE_KEY não configurada no Koyeb!")
        return None, None
    try:
        payer = Keypair.from_base58_string(PRIVATE_KEY_B58)
        # Request Quote
        quote = requests.get(f"https://quote-api.jup.ag/v6/quote?inputMint={input_mint}&outputMint={output_mint}&amount={int(amount)}&slippageBps=1500", timeout=10).json()
        # Request Swap Transaction
        swap_res = requests.post("https://quote-api.jup.ag/v6/swap", json={
            "quoteResponse": quote, "userPublicKey": str(payer.pubkey()), "wrapAndUnwrapSol": True
        }, timeout=10).json()
        
        raw_tx = VersionedTransaction.from_bytes(base58.b58decode(swap_res['swapTransaction']))
        signature = payer.sign_message(raw_tx.message)
        signed_tx = VersionedTransaction.populate(raw_tx.message, [signature])
        tx_id = solana_client.send_raw_transaction(bytes(signed_tx))
        return str(tx_id.value), quote.get('outAmount')
    except Exception as e:
        print(f"Erro no Swap: {e}")
        return None, None

# --- SCANNER DE TOKENS ---
def sniper_scanner():
    processados = set()
    bot.send_message(CHAT_ID, "🚀 **Sniper Silencioso Iniciado!**\nMonitorando novos tokens...")
    
    while True:
        try:
            # Puxa os lançamentos mais recentes do DexScreener
            data = requests.get("https://api.dexscreener.com/token-profiles/latest/v1", timeout=10).json()
            for item in data:
                addr = item.get('tokenAddress')
                if item.get('chainId') == 'solana' and addr not in processados:
                    processados.add(addr)
                    
                    # Tenta comprar 0.1 SOL
                    tx, _ = fazer_swap("So11111111111111111111111111111111111111112", addr, 100_000_000)
                    
                    if tx:
                        bot.send_message(CHAT_ID, f"🛒 **COMPRA EXECUTADA!**\nToken: `{addr}`\n[Ver no Solscan](https://solscan.io/tx/{tx})")
            time.sleep(30)
        except:
            time.sleep(10)

if __name__ == "__main__":
    # Inicia o Scanner em uma thread separada
    t = threading.Thread(target=sniper_scanner)
    t.daemon = True
    t.start()
    
    # Inicia o Flask na porta correta
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port)
