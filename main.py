import os
import time
import threading
import requests
import telebot
from flask import Flask

# ─── CONFIG ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

# Filtros agressivos para capturar momentum inicial
MIN_SCORE     = int(os.getenv("MIN_SCORE", "50"))        # Score mais baixo para pegar o início
MIN_LIQUIDITY = int(os.getenv("MIN_LIQUIDITY", "2500"))  # Liquidez menor para pegar tokens novos
MIN_VOLUME    = int(os.getenv("MIN_VOLUME", "5000"))     # Volume inicial
MIN_BUY_RATIO = float(os.getenv("MIN_BUY_RATIO", "1.5")) # Pelo menos mais compras que vendas
MIN_BUYS      = int(os.getenv("MIN_BUYS", "20"))         # Atividade mínima inicial
DEX_INTERVAL  = 4  # Reduzido para maior velocidade
PUMP_INTERVAL = 8

bot = telebot.TeleBot(TELEGRAM_TOKEN)
app = Flask(__name__)

seen   = set()
alerts = 0
stats  = {"compra": 0, "observar": 0, "ignorado": 0}

def send(msg):
    global alerts
    try:
        # MarkdownV2 é mais sensível, usando Markdown padrão para evitar erros de parse
        bot.send_message(CHAT_ID, msg, parse_mode="Markdown", disable_web_page_preview=True)
        alerts += 1
    except Exception as e:
        print("telegram error:", e)

# ─── SCORE DE MOMENTUM OTIMIZADO ───────────────────────────────────────────
def calcular_score(liq, vol, buys, sells, pc5m, pc1h, pc6h):
    score  = 0
    razoes = []
    riscos = []
    ratio  = buys / max(sells, 1)

    # 1. MOMENTUM DE 5 MINUTOS (O fator mais importante para sniper)
    if pc5m >= 30:
        score += 40
        razoes.append("🚀 EXPLOSÃO M5: +{:.0f}%".format(pc5m))
    elif pc5m >= 10:
        score += 25
        razoes.append("📈 SUBINDO FORTE: +{:.0f}%".format(pc5m))
    elif pc5m < 0:
        score -= 20
        riscos.append("🔻 Queda recente (M5)")

    # 2. PRESSÃO DE COMPRA (Volume de transações)
    if ratio >= 4:
        score += 30
        razoes.append("💎 COMPRADORES DOMINANDO: {:.1f}x".format(ratio))
    elif ratio >= 2:
        score += 15
        razoes.append("✅ Pressão de compra: {:.1f}x".format(ratio))

    # 3. RELAÇÃO VOLUME/LIQUIDEZ (Indica se o dinheiro está girando)
    v_l_ratio = vol / max(liq, 1)
    if v_l_ratio > 3:
        score += 20
        razoes.append("🔥 VOLUME INSANO: {:.1f}x a liquidez".format(v_l_ratio))
    elif v_l_ratio > 1:
        score += 10
        razoes.append("⚡ Volume saudável".format(v_l_ratio))

    # 4. SEGURANÇA MÍNIMA (Liquidez)
    if liq < 3000:
        riscos.append("⚠️ Liquidez Extremamente Baixa")
    
    score = max(0, min(100, score))

    if score >= 70:
        sinal = "🟢 COMPRA AGRESSIVA"
    elif score >= 50:
        sinal = "🟡 MOMENTUM INICIAL"
    else:
        sinal = "⚪ NEUTRO"

    return score, sinal, razoes, riscos

# ─── SCANNER DEXSCREENER ───────────────────────────────────────────────────
def scan_dex():
    global seen, stats
    while True:
        try:
            # Busca tokens da Solana com atividade recente
            url = "https://api.dexscreener.com/latest/dex/search/?q=sol"
            r = requests.get(url, timeout=10)
            if r.status_code != 200: continue

            pairs = r.json().get("pairs", [])
            # Ordenar por variação de 5m para pegar o que está subindo agora
            pairs = sorted(pairs, key=lambda x: x.get("priceChange", {}).get("m5", 0), reverse=True)

            for pair in pairs:
                token = pair.get("baseToken", {}).get("address")
                if not token or token in seen or pair.get("chainId") != "solana":
                    continue

                liq   = pair.get("liquidity", {}).get("usd", 0) or 0
                vol   = pair.get("volume", {}).get("h24", 0) or 0
                buys  = pair.get("txns", {}).get("m5", {}).get("buys", 0) or 0 # Foco em M5
                sells = pair.get("txns", {}).get("m5", {}).get("sells", 0) or 0
                pc5m  = pair.get("priceChange", {}).get("m5", 0) or 0
                pc1h  = pair.get("priceChange", {}).get("h1", 0) or 0
                pc6h  = pair.get("priceChange", {}).get("h6", 0) or 0

                # Filtros de entrada (Abertos para pegar momentum)
                if liq < MIN_LIQUIDITY or pc5m < 2: # Se não subiu pelo menos 2% em 5m, ignora
                    continue
                
                score, sinal, razoes, riscos = calcular_score(liq, vol, buys, sells, pc5m, pc1h, pc6h)

                if score >= MIN_SCORE:
                    seen.add(token)
                    stats["compra" if score >= 60 else "observar"] += 1
                    
                    symbol = pair.get("baseToken", {}).get("symbol", "???")
                    
                    # Links Úteis
                    dex_url = f"https://dexscreener.com/solana/{token}"
                    gmgn_url = f"https://gmgn.ai/sol/token/{token}"
                    # Link para comprar direto em Bots (Acelera muito o trade)
                    trojan_url = f"https://t.me/solana_trojan_bot?start=r-user_{token}"

                    razoes_txt = "\n".join("  " + x for x in razoes)
                    riscos_txt = ("\n\n*⚠️ Riscos:*\n" + "\n".join("  " + x for x in riscos)) if riscos else ""

                    msg = (
                        f"{sinal} *${symbol}*\n"
                        f"🏆 *Score: {score}/100*\n\n"
                        f"📈 *Variação:* 5m: `{pc5m:+.1f}%` | 1h: `{pc1h:+.1f}%`\n"
                        f"💰 *Liquidez:* `${liq:,.0f}`\n"
                        f"📊 *Vol 24h:* `${vol:,.0f}`\n"
                        f"🔄 *M5 Buys:* `{buys}` | *Sells:* `{sells}`\n\n"
                        f"*Motivos:*\n{razoes_txt}"
                        f"{riscos_txt}\n\n"
                        f"🔗 [DexScreener]({dex_url}) | [GMGN]({gmgn_url})\n"
                        f"⚡ [COMPRAR NO TROJAN]({trojan_url})"
                    )
                    send(msg)

        except Exception as e:
            print(f"Error Dex: {e}")
        time.sleep(DEX_INTERVAL)

# O restante das funções (scan_pump, report, app.route) permanecem similares, 
# mas aplique a mesma lógica de score simplificada para o scan_pump se desejar.

@app.route("/")
def home():
    return f"Sniper Ativo | Alertas: {alerts} | Analisados: {len(seen)}"

def start_threads():
    # Envio de mensagem inicial
    bot.send_message(CHAT_ID, "🎯 *Sniper de Momentum Iniciado!* \nBuscando explosões na Solana...", parse_mode="Markdown")
    threading.Thread(target=scan_dex, daemon=True).start()
    # threading.Thread(target=scan_pump, daemon=True).start() # Opcional se focar em Raydium

if __name__ == "__main__":
    start_threads()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
