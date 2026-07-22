"""Server-side dashboard filtering — Python port of the frontend's
buildMockDashboard()/filterMultiplier(). Applies range/segment/team scaling to
the stored base snapshot so GET /dashboard returns already-scaled numbers,
exactly matching what the mock produced."""


def filter_multiplier(rng: str, segment: str, team: str) -> float:
    r = {"today": 0.05, "7d": 0.25, "qtd": 2.9}.get(rng, 1.0)  # default 30d = 1
    s = {"all": 1.0, "card": 0.55, "personal": 0.3, "auto": 0.15}.get(segment, 1.0)
    t = {"all": 1.0, "bot": 0.66, "human": 0.34}.get(team, 1.0)
    return r * s * t


def build_dashboard(base: dict, rng: str, segment: str, team: str) -> dict:
    m = filter_multiplier(rng, segment, team)

    hero = []
    for i, k in enumerate(base["heroKpis"]):
        k = dict(k)
        if i == 0:  # AHT — scale seconds, tighten under the bot-only filter
            secs = round(k["raw"] * (0.55 if team == "bot" else 1.35 if team == "human" else 1))
            k["value"] = f"{secs // 60}m {secs % 60:02d}s"
        else:  # upsell conversion — mild segment influence
            raw = k["raw"] * (1.4 if segment == "personal" else 1.1 if segment == "card" else 1)
            k["value"] = f"{raw:.1f}%"
        hero.append(k)

    kpis = []
    for k in base["kpis"]:
        k = dict(k)
        if k["key"] == "recovered":
            v = 2.48 * m
            k["value"] = f"${v:.2f}M" if v >= 1 else f"${v * 1000:.0f}k"
        elif k["key"] == "calls":
            k["value"] = f"{round(8412 * m):,}"
        kpis.append(k)

    recovery = [{**p, "value": round(p["value"] * m)} for p in base["recoveryTrend"]]
    volume = [
        {
            **p,
            "voice": round(p["voice"] * m * (0.9 if team == "bot" else 1)),
            "whatsapp": round(p["whatsapp"] * m),
            "chat": round(p["chat"] * m),
        }
        for p in base["callVolumeStacked"]
    ]
    bot_vs_human = [{**d, "value": round(d["value"] * m)} for d in base["botVsHuman"]]

    return {
        "heroKpis": hero,
        "kpis": kpis,
        "recoveryTrend": recovery,
        "callVolumeStacked": volume,
        "sentimentDistribution": base["sentimentDistribution"],
        "botVsHuman": bot_vs_human,
        "leaderboard": base["leaderboard"],
        "atRiskAccounts": base["atRiskAccounts"],
    }
