import os
import time
import threading
import requests
import telebot
from flask import Flask
from collections import defaultdict
from datetime import datetime

# ============================================================
# CONFIGURAÇÃO — defina via variáveis de ambiente
# ============================================================
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
CHAT_ID        = os.getenv("CHAT_ID")

# ============================================================
# FILTROS AGRESSIVOS — AJUSTE AQUI
# ============================================================
MIN_LIQUIDITY     = 5_000    # Liquidez mínima em USD
MIN_WHALE_BUYS    = 10       # Mínimo de compras nos últimos 5 min
MIN_VOLUME_M5     = 5_000    # Volume mínimo nos últimos 5 min em USD
MIN_BUY_SELL_RATIO = 2.0     # Ratio compras/vendas (força compradora dominante)
MAX_AGE_MINUTES   = 60       # Ignora tokens com pares criados há mais de X minutos
MIN_PRICE_CHANGE_H1 = 5.0    # Variação positiva mínima na última hora (%)
DEX_INTERVAL      = 1        # Intervalo de scan em segundos (mais rápido possível)
REPORT_INTERVAL   = 7_200    # Relatório a cada 2 horas (segundos)
MAX_SEEN_TOKENS   = 10_000   # Limite do cache para evitar memory leak

# ============================================================
# ESTADO GLOBAL
# ============================================================
seen_tokens      = set()
monitored_tokens = {}   # addr -> {symbol, price_entry, time, liq, vol5m, buys}
report_stats     = {"sent": 0, "whales": 0, "accumulations": 0}
lock             = threading.Lock()

bot = telebot.TeleBot(TELEGRAM_TOKEN, threaded=False)
app = Flask(__name__)

# ============================================================
# UTILITÁRIOS
# ============================================================

def send(msg: str):
    """Envia mensagem para o Telegram com retry."""
    for attempt in range(3):
        try:
            bot.send_message(
                CHAT_ID, msg,
                parse_mode="Markdown",
                disable_web_page_preview=True
            )
            return
        except Exception as e:
            print(f"[TELEGRAM] Tentativa {attempt+1} falhou: {e}")
            time.sleep(1)


def pair_age_minutes(pair: dict) -> float:
    """Retorna há quantos minutos o par foi criado."""
    created_at = pair.get("pairCreatedAt")
    if not created_at:
        return 9999
    age_ms  = time.time() * 1000 - created_at
    return age_ms / 60_000


def buy_sell_ratio(pair: dict) -> float:
    """Calcula ratio de compras vs vendas nos últimos 5 min."""
    m5    = pair.get("txns", {}).get("m5", {})
    buys  = m5.get("buys",  0)
    sells = m5.get("sells", 1)  # evita divisão por zero
    return buys / sells


def classify_signal(buys5m: int, ratio: float, vol5m: float) -> str:
    """Classifica o sinal conforme a força do movimento."""
    if buys5m >= 30 and ratio >= 5 and vol5m >= 20_000:
        return "🚨 MEGA BALEIA"
    if buys5m >= 20 and ratio >= 3:
        return "🐋 BALEIA DETECTADA"
    if buys5m >= 10 and ratio >= 2:
        return "📈 ACUMULAÇÃO FORTE"
    return "📊 MONITORANDO"


def prune_seen_tokens():
    """Remove tokens antigos do cache para evitar crescimento infinito."""
    global seen_tokens
    if len(seen_tokens) > MAX_SEEN_TOKENS:
        seen_tokens = set(list(seen_tokens)[-MAX_SEEN_TOKENS // 2:])

# ============================================================
# SCANNER PRINCIPAL
# ============================================================

def scan():
    print("🐋 WHALE SNIPER V4 — INICIANDO...")
    send(
        "🟢 *WHALE SNIPER V4 ONLINE*\n\n"
        f"⚡ Scan a cada `{DEX_INTERVAL}s`\n"
        f"🔍 Filtros ativos:\n"
        f"  • Mínimo `{MIN_WHALE_BUYS}` compras/5min\n"
        f"  • Ratio compras/vendas ≥ `{MIN_BUY_SELL_RATIO:.1f}x`\n"
        f"  • Liquidez ≥ `${MIN_LIQUIDITY:,}`\n"
        f"  • Volume 5m ≥ `${MIN_VOLUME_M5:,}`\n"
        f"  • Variação 1h ≥ `+{MIN_PRICE_CHANGE_H1:.0f}%`\n"
        f"  • Par criado há no máximo `{MAX_AGE_MINUTES} min`\n\n"
        "📢 Relatório automático a cada 2 horas."
    )

    endpoints = [
        "https://api.dexscreener.com/latest/dex/search?q=solana",
        "https://api.dexscreener.com/latest/dex/search?q=sol+new",
    ]
    ep_index = 0

    while True:
        try:
            url = endpoints[ep_index % len(endpoints)]
            ep_index += 1

            r = requests.get(url, timeout=8)
            if r.status_code != 200:
                time.sleep(DEX_INTERVAL)
                continue

            pairs = r.json().get("pairs") or []
            prune_seen_tokens()

            for pair in pairs:
                if pair.get("chainId") != "solana":
                    continue

                base  = pair.get("baseToken", {})
                addr  = base.get("address")
                symbol = base.get("symbol", "???")

                if not addr or addr in seen_tokens:
                    continue

                # ---- Coleta de métricas ----
                liq        = pair.get("liquidity", {}).get("usd", 0) or 0
                vol5m      = pair.get("volume", {}).get("m5", 0)     or 0
                vol1h      = pair.get("volume", {}).get("h1", 0)     or 0
                buys5m     = pair.get("txns", {}).get("m5", {}).get("buys",  0)
                sells5m    = pair.get("txns", {}).get("m5", {}).get("sells", 1)
                price_usd  = pair.get("priceUsd")
                change_h1  = pair.get("priceChange", {}).get("h1", 0) or 0
                age_min    = pair_age_minutes(pair)
                ratio      = buys5m / max(sells5m, 1)

                if not price_usd:
                    continue
                price = float(price_usd)

                # ---- FILTROS AGRESSIVOS ----
                if liq        < MIN_LIQUIDITY:      continue
                if buys5m     < MIN_WHALE_BUYS:     continue
                if vol5m      < MIN_VOLUME_M5:      continue
                if ratio      < MIN_BUY_SELL_RATIO: continue
                if change_h1  < MIN_PRICE_CHANGE_H1:continue
                if age_min    > MAX_AGE_MINUTES:    continue

                # ---- Passou nos filtros ----
                seen_tokens.add(addr)
                signal = classify_signal(buys5m, ratio, vol5m)

                with lock:
                    monitored_tokens[addr] = {
                        "symbol":      symbol,
                        "price_entry": price,
                        "time":        datetime.utcnow().strftime("%H:%M UTC"),
                        "liq":         liq,
                        "vol5m":       vol5m,
                        "vol1h":       vol1h,
                        "buys5m":      buys5m,
                        "sells5m":     sells5m,
                        "change_h1":   change_h1,
                        "signal":      signal,
                    }
                    report_stats["sent"] += 1
                    if "BALEIA" in signal or "MEGA" in signal:
                        report_stats["whales"] += 1
                    else:
                        report_stats["accumulations"] += 1

                # ---- Links ----
                gmgn_url   = f"https://gmgn.ai/sol/token/{addr}"
                dex_url    = f"https://dexscreener.com/solana/{addr}"
                trojan_url = f"https://t.me/solana_trojan_bot?start=r-user_{addr}"
                pump_url   = f"https://pump.fun/{addr}"

                msg = (
                    f"{signal}\n"
                    f"💎 *${symbol}*  —  `{pair.get('dexId','dex').upper()}`\n\n"
                    f"📄 *CA:* `{addr}`\n\n"
                    f"💲 Preço:   `${price:.10f}`\n"
                    f"📈 Var 1h:  `+{change_h1:.1f}%`\n"
                    f"💧 Liq:     `${liq:,.0f}`\n"
                    f"📊 Vol 5m:  `${vol5m:,.0f}`\n"
                    f"📊 Vol 1h:  `${vol1h:,.0f}`\n"
                    f"🔥 Compras: `{buys5m}` | Vendas: `{sells5m}` | Ratio: `{ratio:.1f}x`\n"
                    f"⏰ Par criado há: `{age_min:.0f} min`\n\n"
                    f"🔗 [GMGN]({gmgn_url})  |  "
                    f"[DEX]({dex_url})  |  "
                    f"[PUMP]({pump_url})\n"
                    f"⚡ [COMPRAR NO TROJAN]({trojan_url})"
                )
                send(msg)

        except Exception as e:
            print(f"[SCAN] Erro: {e}")

        time.sleep(DEX_INTERVAL)

# ============================================================
# RELATÓRIO DE PERFORMANCE (a cada 2 horas)
# ============================================================

def performance_report():
    time.sleep(REPORT_INTERVAL)   # aguarda primeiro ciclo completo
    while True:
        try:
            with lock:
                snapshot = dict(monitored_tokens)
                stats    = dict(report_stats)
                # zera contadores para próximo período
                report_stats["sent"]          = 0
                report_stats["whales"]        = 0
                report_stats["accumulations"] = 0

            if not snapshot:
                send("📊 *RELATÓRIO 2H*\nNenhum token monitorado no período.")
                time.sleep(REPORT_INTERVAL)
                continue

            addrs = list(snapshot.keys())

            # Busca preços atuais em lotes de 30
            current_prices = {}
            for i in range(0, len(addrs), 30):
                batch = ",".join(addrs[i:i+30])
                try:
                    r = requests.get(
                        f"https://api.dexscreener.com/latest/dex/tokens/{batch}",
                        timeout=10
                    )
                    for p in (r.json().get("pairs") or []):
                        a = p.get("baseToken", {}).get("address")
                        v = p.get("priceUsd")
                        if a and v:
                            current_prices[a] = float(v)
                except Exception as e:
                    print(f"[REPORT] Erro preço: {e}")

            # Monta o relatório
            winners   = []
            losers    = []
            no_data   = []

            for addr, info in snapshot.items():
                entry   = info["price_entry"]
                current = current_prices.get(addr, 0)
                if current > 0 and entry > 0:
                    pct = ((current - entry) / entry) * 100
                    row = (pct, info["symbol"], entry, current, info["signal"])
                    if pct >= 0:
                        winners.append(row)
                    else:
                        losers.append(row)
                else:
                    no_data.append(info["symbol"])

            winners.sort(reverse=True)
            losers.sort()

            now = datetime.utcnow().strftime("%d/%m %H:%M UTC")
            report = (
                f"📊 *RELATÓRIO DE PERFORMANCE — {now}*\n"
                f"─────────────────────────\n"
                f"📤 Alertas enviados: `{stats['sent']}`\n"
                f"🐋 Baleias: `{stats['whales']}` | "
                f"📈 Acumulações: `{stats['accumulations']}`\n"
                f"─────────────────────────\n\n"
            )

            if winners:
                report += f"🚀 *VALORIZARAM ({len(winners)})*\n"
                for pct, sym, entry, cur, sig in winners[:15]:
                    bar = "█" * min(int(pct / 10), 20)
                    report += f"  `{pct:+.1f}%` {bar} *${sym}*\n"
                report += "\n"

            if losers:
                report += f"🔻 *CAÍRAM ({len(losers)})*\n"
                for pct, sym, entry, cur, sig in losers[:10]:
                    report += f"  `{pct:+.1f}%` *${sym}*\n"
                report += "\n"

            if no_data:
                report += f"❓ *Sem dados atuais:* {', '.join(['$'+s for s in no_data[:10]])}\n"

            # Melhor e pior token
            if winners:
                best = winners[0]
                report += (
                    f"\n🏆 *Melhor:* `${best[1]}` com `{best[0]:+.1f}%`\n"
                    f"  Entrada: `${best[2]:.10f}` → Atual: `${best[3]:.10f}`"
                )
            if losers:
                worst = losers[0]
                report += (
                    f"\n💀 *Pior:* `${worst[1]}` com `{worst[0]:+.1f}%`"
                )

            send(report)

            # Mantém apenas os últimos 200 tokens no histórico
            with lock:
                if len(monitored_tokens) > 200:
                    keys_to_del = list(monitored_tokens.keys())[:-200]
                    for k in keys_to_del:
                        del monitored_tokens[k]

        except Exception as e:
            print(f"[REPORT] Erro geral: {e}")

        time.sleep(REPORT_INTERVAL)

# ============================================================
# HEALTH CHECK
# ============================================================

@app.route("/")
def health():
    with lock:
        return (
            f"WHALE SNIPER V4 ONLINE | "
            f"Tokens monitorados: {len(monitored_tokens)} | "
            f"Cache seen: {len(seen_tokens)}"
        )

# ============================================================
# ENTRADA
# ============================================================

if __name__ == "__main__":
    threading.Thread(target=scan,               daemon=True).start()
    threading.Thread(target=performance_report, daemon=True).start()
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
