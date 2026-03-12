import os
import time
import threading
import requests
import telebot
from flask import Flask

# ─── CONFIG ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")

# AJUSTE PARA MAIS ALERTAS (Agressividade Máxima)
MIN_SCORE     = 35        # Baixado para não perder oportunidades iniciais
MIN_LIQUIDITY = 1000      # Aceita tokens bem no começo da pool
MIN_BUYS_M5   = 5         # Se tiver 5 compras em 5min, já avaliamos
DEX_INTERVAL  = 2         # Scan quase em tempo real

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

# ─── ANÁLISE DE PROMESSA (PROMISSOR) ──────────────────────────────────────
def analisar_promessa(pair):
    score = 0
    razoes = []
    
    # Dados de 5 minutos e 1 hora
    m5 = pair.get("txns", {}).get("m5", {})
    buys = m5.get("buys", 0)
    sells = m5.get("sells", 0)
    pc5m = pair.get("priceChange", {}).get("m5", 0)
    pc1h = pair.get("priceChange", {}).get("h1", 0)
    
    ratio = buys / max(sells, 1)

    # 1. NOVO VOLUME ENTRANDO (Ouro)
    if buys > 30:
        score += 40
        razoes.append(f"🔥 FOMO DETECTADO: {buys} compras em 5m")
    elif buys > 10:
        score += 20
        razoes.append(f"✅ Volume entrando")

    # 2. PREÇO EM ESCADA (Sem dump pesado)
    if pc5m > 10 and pc5m < 100: # Se subiu muito rápido (>100%), pode ser topo
        score += 30
        razoes.append(f"📈 Crescimento Saudável: +{pc5m}%")
    
    # 3. DOMINAÇÃO DE COMPRA
    if ratio > 3:
        score += 30
        razoes.append(f"💎 Baleias comprando ({ratio:.1f}x mais que venda)")

    if score >= MIN_SCORE:
        return score, razoes
    return None, None

# ─── SCANNER OTIMIZADO ─────────────────────────────────────────────────────
def scan_dex():
    global seen
    # Endpoint de tokens recentes e com volume na Solana
    # Mudamos para buscar os pares mais ativos diretamente
    url = "https://api.dexscreener.com/latest/dex/tokens/solana" 
    # Alternativa: "https://api.dexscreener.com/latest/dex/search/?q=sol"
    
    print("Sniper Agressivo rodando...")
    
    while True:
        try:
            # Usando busca por 'sol' para pegar tudo que é par SOL recente
            r = requests.get("https://api.dexscreener.com/latest/dex/search/?q=sol", timeout=5)
            if r.status_code != 200: continue

            pairs = r.json().get("pairs", [])
            # Prioriza os que tiveram mudança de preço recente
            pairs = sorted(pairs, key=lambda x: x.get("priceChange", {}).get("m5", 0), reverse=True)

            for pair in pairs:
                token_addr = pair.get("baseToken", {}).get("address")
                symbol = pair.get("baseToken", {}).get("symbol", "???")
                liq = pair.get("liquidity", {}).get("usd", 0)
                
                if not token_addr or token_addr in seen: continue
                if liq < MIN_LIQUIDITY: continue

                score, razoes = analisar_promessa(pair)

                if score:
                    seen.add(token_addr)
                    
                    # CORREÇÃO DO LINK GMGN (Usando o formato de visualização direta)
                    # Adicionado ?chain=sol para forçar o app/site a entender a rede
                    gm_link = f"https://gmgn.ai/sol/token/{token_addr}?chain=sol"
                    ds_link = f"https://dexscreener.com/solana/{token_addr}"
                    
                    # Trojan para compra instantânea
                    tj_link = f"https://t.me/solana_trojan_bot?start=r-user_{token_addr}"

                    razoes_txt = "\n".join([f"  • {r}" for r in razoes])
                    
                    msg = (
                        f"🚀 *OPORTUNIDADE DETECTADA: ${symbol}*\n"
                        f"🏆 *Confiança: {score}/100*\n\n"
                        f"*Por que entrar:* \n{razoes_txt}\n\n"
                        f"💰 Liquidez: `${liq:,.0f}`\n"
                        f"📊 Vol 24h: `${pair.get('volume', {}).get('h24', 0):,.0f}`\n\n"
                        f"🔗 [ABRIR NO GMGN]({gm_link})\n"
                        f"📈 [DexScreener]({ds_link})\n"
                        f"⚡ [COMPRA RÁPIDA (Trojan Bot)]({tj_link})"
                    )
                    send(msg)

        except Exception as e:
            print(f"Erro: {e}")
        
        time.sleep(DEX_INTERVAL)

@app.route("/")
def health():
    return f"Sniper Online - Tokens vistos: {len(seen)}"

if __name__ == "__main__":
    threading.Thread(target=scan_dex, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
