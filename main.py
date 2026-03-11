import os
import time
import threading
import requests
import telebot
from flask import Flask

# ─── CONFIG ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# FILTROS ULTRA AGRESSIVOS (Abaixe se quiser ainda mais sinais)
MIN_SCORE     = int(os.getenv("MIN_SCORE", "40"))       
MIN_LIQUIDITY = int(os.getenv("MIN_LIQUIDITY", "1500")) # Pegar tokens bem no início
MIN_BUYS_M5   = int(os.getenv("MIN_BUYS_M5", "10"))     # Mínimo de 10 compras nos últimos 5 min
DEX_INTERVAL  = 3  # Scan super rápido

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

seen = set()
alerts = 0

def send(msg):
    global alerts
    try:
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
        alerts += 1
    except Exception as e:
        print(f"Telegram Error: {e}")

# ─── CÁLCULO DE MOMENTUM ──────────────────────────────────────────────────
def analisar_momentum(pair):
    score = 0
    razoes = []
    
    # Extração de dados (foco em 5 minutos)
    m5_data = pair.get("txns", {}).get("m5", {})
    buys = m5_data.get("buys", 0)
    sells = m5_data.get("sells", 0)
    pc5m = pair.get("priceChange", {}).get("m5", 0)
    liq = pair.get("liquidity", {}).get("usd", 0)
    vol_h24 = pair.get("volume", {}).get("h24", 0)
    
    ratio = buys / max(sells, 1)

    # 1. ACELERAÇÃO DE PREÇO (Peso 40)
    if pc5m >= 20:
        score += 40
        razoes.append(f"🚀 EXPLOSÃO: +{pc5m}% (5m)")
    elif pc5m >= 5:
        score += 20
        razoes.append(f"📈 SUBINDO: +{pc5m}% (5m)")

    # 2. PRESSÃO DE COMPRA (Peso 40)
    if ratio >= 5:
        score += 40
        razoes.append(f"💎 COMPRA EXTREMA: {ratio:.1f}x")
    elif ratio >= 2:
        score += 20
        razoes.append(f"✅ Volume de Compra: {ratio:.1f}x")

    # 3. ATIVIDADE (Peso 20)
    if buys > 50:
        score += 20
        razoes.append(f"🔥 MUITA ATIVIDADE: {buys} trades/5m")
    elif buys > 20:
        score += 10

    # Sinalizador
    if score >= 70:
        sinal = "🟢 COMPRA AGRESSIVA"
    elif score >= 40:
        sinal = "🟡 OBSERVANDO MOMENTUM"
    else:
        return None, None, None # Descarta se for fraco

    return score, sinal, razoes

# ─── SCANNER PRINCIPAL ─────────────────────────────────────────────────────
def scan_dex():
    global seen
    print("Sniper rodando...")
    
    while True:
        try:
            # Pegando os tokens mais ativos na Solana via DexScreener
            url = "https://api.dexscreener.com/latest/dex/search/?q=sol"
            r = requests.get(url, timeout=5)
            if r.status_code != 200: continue

            pairs = r.json().get("pairs", [])
            
            for pair in pairs:
                token_addr = pair.get("baseToken", {}).get("address")
                symbol = pair.get("baseToken", {}).get("symbol", "???")
                liq = pair.get("liquidity", {}).get("usd", 0)
                
                # Filtros Básicos de Segurança e Liquidez
                if not token_addr or token_addr in seen: continue
                if liq < MIN_LIQUIDITY: continue
                if pair.get("txns", {}).get("m5", {}).get("buys", 0) < MIN_BUYS_M5: continue

                score, sinal, razoes = analisar_momentum(pair)

                if score and score >= MIN_SCORE:
                    seen.add(token_addr)
                    
                    # Links de Ação
                    gmgn = f"https://gmgn.ai/sol/token/{token_addr}"
                    ds = f"https://dexscreener.com/solana/{token_addr}"
                    # Link para o bot Trojan (execução mais rápida que existe)
                    trojan = f"https://t.me/solana_trojan_bot?start=r-user_{token_addr}"

                    razoes_txt = "\n".join([f"  • {r}" for r in razoes])
                    
                    msg = (
                        f"{sinal} *${symbol}*\n"
                        f"🏆 *SCORE: {score}/100*\n\n"
                        f"*Análise:* \n{razoes_txt}\n\n"
                        f"💰 Liquidez: `${liq:,.0f}`\n"
                        f"📊 Vol 24h: `${pair.get('volume', {}).get('h24', 0):,.0f}`\n\n"
                        f"🔗 [GMGN]({gmgn}) | [DexScreener]({ds})\n"
                        f"⚡ [COMPRAR AGORA (Trojan)]({trojan})"
                    )
                    send(msg)

        except Exception as e:
            print(f"Erro no loop: {e}")
        
        time.sleep(DEX_INTERVAL)

@app.route("/")
def health_check():
    return f"Sniper Online - Alertados: {len(seen)}"

if __name__ == "__main__":
    # Inicia o scanner em uma thread separada
    threading.Thread(target=scan_dex, daemon=True).start()
    
    # Rodar o servidor Flask
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
