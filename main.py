# ============================================================
# FILTROS QUANT — AJUSTADOS
# ============================================================

MIN_LIQ      = 1_800
MAX_LIQ      = 120_000

MIN_BUYS     = 5
MAX_BUYS     = 1500

MIN_RATIO    = 1.15
MIN_SELLS    = 1

MIN_VOL      = 250

MIN_AGE      = 0.03
MAX_AGE      = 20

MIN_M5       = 0.2
MAX_M5       = 150.0

MIN_H1       = -25.0
MAX_H1       = 180.0

REPORT_INTERVAL = 7200

# ============================================================
# ENDPOINTS — EXPANDIDOS
# ============================================================

ENDPOINTS = [

    "https://api.dexscreener.com/latest/dex/search?q=solana",
    "https://api.dexscreener.com/latest/dex/search?q=solana+new",
    "https://api.dexscreener.com/latest/dex/search?q=solana+meme",
    "https://api.dexscreener.com/latest/dex/search?q=pumpfun",
    "https://api.dexscreener.com/latest/dex/search?q=pump.fun",
    "https://api.dexscreener.com/latest/dex/search?q=raydium",
    "https://api.dexscreener.com/latest/dex/search?q=raydium+new",
    "https://api.dexscreener.com/latest/dex/search?q=moonshot",
    "https://api.dexscreener.com/latest/dex/search?q=moonshot+sol",
    "https://api.dexscreener.com/latest/dex/search?q=degen",
    "https://api.dexscreener.com/latest/dex/search?q=memecoin",
    "https://api.dexscreener.com/latest/dex/search?q=solana+trending",
    "https://api.dexscreener.com/latest/dex/search?q=bonk",
]

# ============================================================
# SCORE NOVO — SUBSTITUA SUA FUNÇÃO sinal()
# ============================================================

def sinal(data, g):

    pontos = 0

    ratio      = data["ratio"]
    buys       = data["buys"]
    age        = data["age"]
    h1         = data["h1"]
    vol_accel  = data["vol_accel"]

    smart      = g.get("smart", 0)
    holders    = g.get("holders", 0)

    top10      = g.get("top10", 0)

    top10_pct = (
        float(top10) * 100
        if float(top10) <= 1
        else float(top10)
    ) if top10 else 0

    # ========================================================
    # SMART MONEY
    # ========================================================

    if smart >= 5:
        pontos += 7
    elif smart >= 3:
        pontos += 5
    elif smart >= 1:
        pontos += 2

    # ========================================================
    # BUY PRESSURE
    # ========================================================

    if ratio >= 5:
        pontos += 6
    elif ratio >= 3:
        pontos += 5
    elif ratio >= 2:
        pontos += 3
    else:
        pontos += 1

    # ========================================================
    # EARLY ENTRY
    # ========================================================

    if age <= 3:
        pontos += 6
    elif age <= 6:
        pontos += 5
    elif age <= 10:
        pontos += 3

    # ========================================================
    # HOLDERS
    # ========================================================

    if holders >= 300:
        pontos += 6
    elif holders >= 150:
        pontos += 4
    elif holders >= 80:
        pontos += 2

    # ========================================================
    # VOLUME BEFORE PRICE
    # ========================================================

    if vol_accel >= 4 and h1 <= 20:
        pontos += 7

    elif vol_accel >= 2.5 and h1 <= 35:
        pontos += 5

    elif vol_accel >= 1.8:
        pontos += 3

    # ========================================================
    # BUY CLUSTER
    # ========================================================

    if buys >= 40:
        pontos += 5
    elif buys >= 20:
        pontos += 4
    elif buys >= 10:
        pontos += 2

    # ========================================================
    # TOP10
    # ========================================================

    if top10_pct <= 25:
        pontos += 4
    elif top10_pct <= 35:
        pontos += 2
    elif top10_pct >= 45:
        pontos -= 5

    # ========================================================
    # CLASSIFICAÇÃO
    # ========================================================

    elite = (

        smart >= 3 and
        ratio >= 3 and
        age <= 8 and
        top10_pct <= 30 and
        vol_accel >= 2.5
    )

    if elite:

        return (
            "🚨",
            "ELITE WHALE ENTRY",
            "Possível entrada institucional"
        )

    elif pontos >= 26:

        return (
            "🟢",
            "VERDE — SMART MONEY",
            "Whales entrando cedo"
        )

    elif pontos >= 18:

        return (
            "🟡",
            "AMARELO — MOMENTUM",
            "Volume saudável"
        )

    else:

        return (
            "🔴",
            "VERMELHO — RISCO",
            "Possível manipulação"
        )

# ============================================================
# PROCESSAR — ALTERAÇÕES IMPORTANTES
# ============================================================

# ADICIONE DEPOIS DE:

vol_accel = 0

if vol1h > 0:
    vol_accel = vol5m / max(vol1h / 12, 1)

# ============================================================
# STEALTH BUY
# ============================================================

stealth_buy = (

    buys >= 5 and
    ratio >= 2 and
    age <= 4 and
    vol_accel >= 2
)

# ============================================================
# WHALE MODE
# ============================================================

whale_mode = (

    buys >= 10 and
    ratio >= 2 and
    vol_accel >= 1.8
)

# ============================================================
# ULTRA EARLY
# ============================================================

ultra_early = (

    age <= 5 and
    buys >= 6 and
    m5 >= 1
)

# ============================================================
# FILTRO FINAL
# ============================================================

if not whale_mode and not ultra_early and not stealth_buy:
    return

# ============================================================
# BLOQUEAR TOKEN JÁ EXPLODIDO
# ============================================================

if h1 >= 180 and age >= 10:
    return

# ============================================================
# SELL RATIO — AJUSTADO
# ============================================================

if sells > 0:

    sell_ratio = sells / max(buys, 1)

    if sell_ratio < 0.005:
        pass

    elif sell_ratio > 0.95:
        return

# ============================================================
# TOP10 — ANTI RUG
# ============================================================

top10 = g.get("top10", 0)

top10_pct = (
    float(top10) * 100
    if float(top10) <= 1
    else float(top10)
) if top10 else 0

if top10_pct >= 45:
    return

# ============================================================
# ALTERE A CHAMADA DO SCORE PARA:
# ============================================================

emoji, label, desc = sinal({

    "ratio": ratio,
    "buys": buys,
    "age": age,
    "h1": h1,
    "vol_accel": vol_accel

}, g)

# ============================================================
# VELOCIDADE DO SCAN
# ============================================================

# TROQUE:

time.sleep(0.25)

# POR:

time.sleep(0.08)

# ============================================================
# THREADS — MAIS MONITORAMENTO
# ============================================================

# TROQUE:

for i in range(12):

# POR:

for i in range(20):
