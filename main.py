import os
import time
import threading
import requests
import telebot
from flask import Flask

# ─── CONFIG ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

MIN_SCORE     = 35        
MIN_LIQUIDITY = 1000      
DEX_INTERVAL  = 2         

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

seen = set()
alerts = 0

def send(msg):
    global alerts
    try:
        # Usando parse_mode Markdown para permitir a cópia rápida do contrato
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
        alerts += 1
    except Exception as e:
        print(f"Telegram Error: {e}")

def analisar_promessa(pair):
    score = 0
    razoes = []
    m5 = pair.get("txns", {}).get("m5", {})
    buys = m5.get("buys", 0)
    pc5m = pair.get("priceChange", {}).get("m5", 0)
    
    if buys > 10:
        score += 40
        razoes.append(f"🔥 Volume entrando: {buys} buys/5m")
    if 5 < pc5m < 80:
        score += 30
        razoes.append(f"📈 Subida Constante: +{pc5m}%")
    
    if score >= MIN_SCORE:
        return score, razoes
    return None, None

def scan_dex():
    global seen
    print("Sniper Agressivo rodando...")
    
    while True:
        try:
            # Busca ampliada para pegar novos pares SOL
            r = requests.get("https://api.dexscreener.com/latest/dex/search/?q=sol", timeout=5)
            if r.status_code != 200: continue

            pairs = r.json().get("pairs", [])
            for pair in pairs:
                token_addr = pair.get("baseToken", {}).get("address")
                symbol = pair.get("baseToken", {}).get("symbol", "???")
                liq = pair.get("liquidity", {}).get("usd", 0)
                
                if not token_addr or token_addr in seen: continue
                if liq < MIN_LIQUIDITY: continue

                score, razoes = analisar_promessa(pair)

                if score:
                    seen.add(token_addr)
                    
                    # --- CORREÇÃO DOS LINKS ---
                    # Link de Swap direto costuma ser mais estável que o link de chart
                    gm_link = f"https://gmgn.ai/sol/token/{token_addr}"
                    ds_link = f"https://dexscreener.com/solana/{token_addr}"
                    tj_link = f"https://t.me/solana_trojan_bot?start=r-user_{token_addr}"

                    razoes_txt = "\n".join([f"  • {r}" for r in razoes])
                    
                    # Mensagem otimizada para Copiar Contrato e Negociar
                    msg = (
                        f"🚀 *OPORTUNIDADE: ${symbol}*\n"
                        f"🏆 *Score: {score}/100*\n\n"
                        f"📝 *Contrato (Clique p/ copiar):*\n"
                        f"`{token_addr}`\n\n"
                        f"*Análise:*\n{razoes_txt}\n\n"
                        f"💰 Liq: `${liq:,.0f}` | Vol: `${pair.get('volume', {}).get('h24', 0):,.0f}`\n\n"
                        f"🔗 [ABRIR GMGN]({gm_link})\n"
                        f"📈 [DexScreener]({ds_link})\n"
                        f"⚡ [TROJAN BOT (Compra)]({tj_link})"
                    )
                    send(msg)

        except Exception as e:
            print(f"Erro: {e}")
        
        time.sleep(DEX_INTERVAL)

@app.route("/")
def health():
    return f"Sniper Online - Contratos Monitorados: {len(seen)}"

if __name__ == "__main__":
    threading.Thread(target=scan_dex, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
