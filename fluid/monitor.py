#!/usr/bin/env python3
"""FLUID token monitor v0.1. Standard-library-only; no credentials required."""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data"
HEADERS = {"User-Agent": "fluid-investor-monitor/0.1", "Accept": "application/json"}
if os.environ.get("COINGECKO_DEMO_API_KEY"):
    HEADERS["x-cg-demo-api-key"] = os.environ["COINGECKO_DEMO_API_KEY"]

URLS = {
    "market": "https://api.coingecko.com/api/v3/coins/markets",
    "combined_tvl": "https://api.llama.fi/protocol/fluid",
    "lending_tvl": "https://api.llama.fi/protocol/fluid-lending",
    "dex_tvl": "https://api.llama.fi/protocol/fluid-dex",
    "fees": "https://api.llama.fi/summary/fees/fluid?dataType=dailyFees",
    "revenue": "https://api.llama.fi/summary/fees/fluid?dataType=dailyRevenue",
    "holders_revenue": "https://api.llama.fi/summary/fees/fluid?dataType=dailyHoldersRevenue",
    "lending_revenue": "https://api.llama.fi/summary/fees/fluid-lending?dataType=dailyRevenue",
    "dex_revenue": "https://api.llama.fi/summary/fees/fluid-dex?dataType=dailyRevenue",
    "dex_volume": "https://api.llama.fi/summary/dexs/fluid-dex",
    "governance": "https://gov.fluid.io/latest.json",
}


def numeric(v):
    """Preserve zero; reject booleans, invalid numbers and NaN."""
    try:
        if isinstance(v, bool) or v is None:
            return None
        f = float(v)
        return f if -float("inf") < f < float("inf") else None
    except (TypeError, ValueError):
        return None


def percentage(new, old):
    a, b = numeric(new), numeric(old)
    return 100 * (a / b - 1) if a is not None and b is not None and b > 0 else None


def get_json(url, params=None):
    if params:
        url += ("&" if "?" in url else "?") + urlencode(params)
    for attempt in range(3):
        try:
            with urlopen(Request(url, headers=HEADERS), timeout=25) as r:
                return json.load(r)
        except (HTTPError, URLError, TimeoutError, ValueError) as ex:
            if attempt == 2 or (isinstance(ex, HTTPError) and ex.code not in (429, 500, 502, 503, 504)):
                raise RuntimeError(f"{type(ex).__name__}: {ex}") from ex
            time.sleep(2 ** attempt)


def last_observation(chart):
    if not isinstance(chart, list):
        return None
    for item in reversed(chart):
        if isinstance(item, (list, tuple)) and len(item) > 1 and numeric(item[1]) is not None:
            try:
                return datetime.fromtimestamp(float(item[0]), timezone.utc).isoformat()
            except (ValueError, TypeError, OSError, OverflowError):
                pass
    return None


def extract_tvl(payload):
    chart = payload.get("tvl") or []
    current, observed = None, None
    for row in reversed(chart):
        amount = numeric(row.get("totalLiquidityUSD")) if isinstance(row, dict) else None
        if amount is not None:
            current = amount
            observed = datetime.fromtimestamp(row["date"], timezone.utc).isoformat() if numeric(row.get("date")) is not None else None
            break
    # Do not add borrowed, staking or pool2 buckets to TVL (double-counting).
    chains = {}
    for chain, amount in (payload.get("currentChainTvls") or {}).items():
        if any(s in chain.lower() for s in ("borrowed", "staking", "pool2", "vesting")):
            continue
        if numeric(amount) is not None:
            chains[chain] = numeric(amount)
    return {"tvl_usd": current, "observed_at": observed, "chain_tvl_usd_non_additive": chains}


def extract_flow(payload):
    if not isinstance(payload, dict):
        return {"status": "UNKNOWN"}
    out = {"status": "OBSERVED", "total_24h_usd": numeric(payload.get("total24h")),
           "total_7d_usd": numeric(payload.get("total7d")),
           "total_30d_usd": numeric(payload.get("total30d")),
           "previous_7d_usd": numeric(payload.get("total14dto7d")),
           "previous_30d_usd": numeric(payload.get("total60dto30d")),
           "observed_at": last_observation(payload.get("totalDataChart"))}
    out["change_7d_vs_prior_7d_pct"] = percentage(out["total_7d_usd"], out["previous_7d_usd"])
    out["change_30d_vs_prior_30d_pct"] = percentage(out["total_30d_usd"], out["previous_30d_usd"])
    if out["total_30d_usd"] is None and out["total_7d_usd"] is None:
        out["status"] = "UNKNOWN"
    return out


def extract_market(payload):
    rows = {str(row.get("id")): row for row in payload if isinstance(row, dict)} if isinstance(payload, list) else {}
    out = {}
    for coin in ("instadapp", "bitcoin", "ethereum"):
        x = rows.get(coin, {})
        out["fluid" if coin == "instadapp" else coin] = {
            "price_usd": numeric(x.get("current_price")),
            "market_cap_usd": numeric(x.get("market_cap")),
            "price_change_24h_pct": numeric(x.get("price_change_percentage_24h")),
            "price_change_7d_pct": numeric(x.get("price_change_percentage_7d_in_currency")),
            "price_change_30d_pct": numeric(x.get("price_change_percentage_30d_in_currency")),
            "observed_at": x.get("last_updated"),
        }
        if coin == "instadapp":
            out["fluid"].update({
                "volume_24h_usd": numeric(x.get("total_volume")),
                "fdv_usd": numeric(x.get("fully_diluted_valuation")),
                "circulating_supply": numeric(x.get("circulating_supply")),
                "total_supply": numeric(x.get("total_supply")),
                "max_supply": numeric(x.get("max_supply"))})
    f = out["fluid"]
    for period in ("7d", "30d"):
        fp = f["price_change_" + period + "_pct"]
        bp = out["bitcoin"]["price_change_" + period + "_pct"]
        # Relative performance of price ratios, not simple difference of % returns.
        out["fluid_vs_btc_" + period + "_pct"] = (100 * ((1+fp/100)/(1+bp/100)-1)
                                                       if fp is not None and bp is not None and bp > -100 else None)
    f["circulating_supply_pct_of_total"] = (100 * f["circulating_supply"] / f["total_supply"]
                                             if f["circulating_supply"] is not None and f["total_supply"] and f["total_supply"] > 0 else None)
    return out


def governance_topics(payload):
    topics = (payload.get("topic_list") or {}).get("topics") or []
    rows = []
    for t in topics[:25]:
        title = str(t.get("title") or "")
        key = any(s in title.lower() for s in ("buyback", "resolv", "exploit", "incident", "security", "treasury", "grant", "revenue"))
        if key:
            rows.append({"title": title, "last_posted_at": t.get("last_posted_at"),
                         "url": f"https://gov.fluid.io/t/{t.get('slug')}/{t.get('id')}",
                         "classification": "UNVERIFIED_HEADLINE_REQUIRES_REVIEW"})
    return rows[:12]


def source_health(source, raw, now):
    if isinstance(raw, Exception):
        return {"status": "ERROR", "url": URLS[source], "error": str(raw)[:240]}
    if raw is None:
        return {"status": "MISSING", "url": URLS[source]}
    observed = None
    if source == "market":
        rows = raw if isinstance(raw, list) else []
        observed = next((r.get("last_updated") for r in rows if isinstance(r, dict) and r.get("id") == "instadapp"), None)
    elif source.endswith("tvl"):
        observed = extract_tvl(raw).get("observed_at")
    elif source != "governance":
        observed = last_observation(raw.get("totalDataChart") if isinstance(raw, dict) else None)
    status = "FETCHED_OBSERVATION_UNDATED"
    if observed:
        try:
            dt = datetime.fromisoformat(observed.replace("Z", "+00:00"))
            age = (now-dt).total_seconds()/3600
            # Daily close data may be ~48h behind at provider; display staleness explicitly.
            status = "STALE" if age > (48 if source == "market" else 72) else "FRESH"
        except (ValueError, TypeError):
            status = "FETCHED_INVALID_TIMESTAMP"
    return {"status": status, "url": URLS[source], "observed_at": observed,
            "retrieved_at": now.isoformat()}


def evaluate(market, business, capture, health, governance):
    reasons, warnings = [], []
    fluid = market.get("fluid", {})
    tvl = business.get("combined", {}).get("tvl_usd")
    revenue = business.get("protocol_revenue", {}).get("total_30d_usd")
    holder = capture.get("holders_revenue", {}).get("total_30d_usd")
    req = ("market", "combined_tvl", "revenue", "holders_revenue")
    missing = [s for s in req if health.get(s, {}).get("status") in ("ERROR", "MISSING", "STALE")]
    if fluid.get("price_usd") is None or tvl is None or revenue is None or holder is None:
        missing.extend(["essential_parsed_metric_unavailable"])
    if missing:
        warnings.append("핵심 데이터 누락/지연: " + ", ".join(sorted(set(missing))))
    r_delta = business.get("protocol_revenue", {}).get("change_30d_vs_prior_30d_pct")
    tvl_chg = business.get("tvl_change_30d_pct")
    if r_delta is not None and r_delta < -30:
        reasons.append("Protocol revenue 30d vs previous 30d below -30%")
    if tvl_chg is not None and tvl_chg < -20:
        reasons.append("Combined TVL 30d change below -20%")
    if governance:
        warnings.append("최신 거버넌스 관련 제목은 검토 전까지 사실 확정 금지")
    capture_state = ("NO_MEASURED_HOLDER_DISTRIBUTION" if holder == 0 else
                     "HOLDER_REVENUE_OBSERVED" if holder is not None and holder > 0 else "UNKNOWN")
    # A governance proposal or DefiLlama holder revenue never proves an on-chain buyback.
    if missing:
        action = "DATA_INSUFFICIENT"
    elif reasons:
        action = "REDUCE_REVIEW_REQUIRED"
    else:
        action = "HOLD_NO_ADD"
    return {
        "current_action": action, "action_is_not_trade_execution": True,
        "buyback_verified_live": False, "buyback_status": "UNVERIFIED_AFTER_2026_05_PAUSE_PROPOSAL",
        "token_capture_state": capture_state, "evidence_confidence": "LOW" if missing else "MEDIUM",
        "price_forecast_confidence": "LOW", "risk_triggers": reasons,
        "data_quality_warnings": warnings,
        "thesis": {
            "F1_real_usage": "OBSERVED" if tvl is not None else "UNKNOWN",
            "F2_lending_utilization": "UNKNOWN_NO_ACTIVE_LOANS_ADAPTER",
            "F3_protocol_revenue": "OBSERVED" if revenue is not None else "UNKNOWN",
            "F4_competitive_moat": "UNKNOWN_NOT_NORMALIZED",
            "F5_token_value_capture": capture_state,
            "F6_security_solvency": "UNVERIFIED_CURRENT_EXPOSURE",
            "F7_supply_and_valuation": "OBSERVED" if fluid.get("fdv_usd") is not None else "UNKNOWN"
        },
        "invalidations_to_check": ["Unresolved bad debt or deposit loss", "Sustained loan/TVL contraction and revenue collapse", "Governance blocks token value accrual indefinitely"]
    }


def thirty_day_change(chart):
    if not isinstance(chart, list) or not chart:
        return None
    rows = [(numeric(x.get("date")), numeric(x.get("totalLiquidityUSD"))) for x in chart if isinstance(x, dict)]
    rows = [(d, v) for d, v in rows if d is not None and v is not None]
    if not rows:
        return None
    end = rows[-1][0]
    prior = next((v for d, v in reversed(rows) if d <= end - 30 * 86400), None)
    return percentage(rows[-1][1], prior)


def collect(fetch=get_json, at=None):
    now = at or datetime.now(timezone.utc)
    raw, health = {}, {}
    for source, url in URLS.items():
        try:
            params = ({"vs_currency":"usd", "ids":"instadapp,bitcoin,ethereum",
                       "price_change_percentage":"7d,30d", "per_page":3} if source == "market" else None)
            raw[source] = fetch(url, params) if params else fetch(url)
        except Exception as ex:
            raw[source] = ex
        health[source] = source_health(source, raw[source], now)
    usable = lambda k: None if isinstance(raw[k], Exception) else raw[k]
    market = extract_market(usable("market"))
    business = {
        "combined": extract_tvl(usable("combined_tvl") or {}),
        "lending_component": extract_tvl(usable("lending_tvl") or {}),
        "dex_component": extract_tvl(usable("dex_tvl") or {}),
        "protocol_fees": extract_flow(usable("fees")),
        "protocol_revenue": extract_flow(usable("revenue")),
        "lending_revenue_component": extract_flow(usable("lending_revenue")),
        "dex_revenue_component": extract_flow(usable("dex_revenue")),
        "dex_volume": extract_flow(usable("dex_volume")),
        "important": "Combined and component TVL/revenue are NOT summed. Fees are not revenue. Borrow interest paid to suppliers is not tokenholder earnings.",
        "tvl_change_30d_pct": thirty_day_change((usable("combined_tvl") or {}).get("tvl"))
    }
    capture = {
        "holders_revenue": extract_flow(usable("holders_revenue")),
        "actual_buybacks_usd_30d": None,
        "actual_burns_tokens_30d": None,
        "buyback_pause_2026_05_11": "GOVERNANCE_PROPOSAL_DOCUMENTED_NOT_LIVE_VERIFIED",
        "token_capture_mechanism_verified_current": False,
        "source": "https://gov.fluid.io/t/post-mortem-treasury-actions-and-forward-strategy-following-resolv-incident/1774"
    }
    gov = governance_topics(usable("governance") or {})
    decision = evaluate(market, business, capture, health, gov)
    fluid = market["fluid"]
    rev30 = business["protocol_revenue"].get("total_30d_usd")
    # DefiLlama protocol revenue, NOT holders revenue or net profit.
    valuation = {
        "fdv_to_protocol_revenue_runrate": (fluid["fdv_usd"] / (rev30 * 12)
                                            if fluid.get("fdv_usd") is not None and rev30 is not None and rev30 > 0 else None),
        "annualization_warning": "Last 30 days x12 is a run rate, not a forecast or corporate earnings multiple."
    }
    return {"schema_version":"1.0", "asset":"FLUID", "generated_at":now.isoformat(),
            "market":market, "business":business, "token_capture":capture,
            "valuation":valuation, "governance_headline_watch":gov,
            "source_health":health, "decision":decision,
            "scenarios":{"bear": "Revenue contraction + additional bad debt; token capture remains absent",
                         "base": "Protocol recovery, token capture unconfirmed; no numeric return forecast",
                         "bull": "Growth plus externally verified sustained buybacks or equivalent holder-rights change",
                         "confidence":"LOW", "numeric_targets_locked":False},
            "methodology":"Observed data vs governance proposals vs hypothetical scenarios are distinct. No automatic trading."}


def weekly(daily, records):
    dated = sorted((x for x in records if isinstance(x, dict)), key=lambda x:x.get("generated_at", ""))
    latest = dated[-1] if dated else daily
    early = dated[-8] if len(dated) >= 8 else dated[0] if dated else None
    def dig(obj, *keys):
        for k in keys:
            obj = obj.get(k, {}) if isinstance(obj, dict) else {}
        return numeric(obj) if not isinstance(obj, dict) else None
    price_start = dig(early, "market", "fluid", "price_usd") if early else None
    price_end = dig(latest, "market", "fluid", "price_usd")
    tvl_start = dig(early, "business", "combined", "tvl_usd") if early else None
    tvl_end = dig(latest, "business", "combined", "tvl_usd")
    return {"schema_version":"1.0", "asset":"FLUID", "generated_at":daily["generated_at"],
            "daily_observations":len(dated), "is_full_seven_day_sample":len(dated)>=8,
            "sample_based_fluid_price_change_pct":percentage(price_end, price_start) if len(dated)>=8 else None,
            "sample_based_tvl_change_pct":percentage(tvl_end, tvl_start) if len(dated)>=8 else None,
            "revenue_30d_vs_prior_30d_pct": daily["business"]["protocol_revenue"].get("change_30d_vs_prior_30d_pct"),
            "dex_volume_7d_vs_prior_7d_pct": daily["business"]["dex_volume"].get("change_7d_vs_prior_7d_pct"),
            "latest_decision":daily["decision"],
            "warning":"Sample changes need >=8 separate daily snapshots. Rolling 7d/30d provider windows are not sampled snapshots."}


def save_report(report):
    DATA.mkdir(parents=True, exist_ok=True)
    history = DATA / "history"
    history.mkdir(exist_ok=True)
    day = report["generated_at"][:10]
    (history / f"{day}.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    (DATA / "latest_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    records = []
    for f in sorted(history.glob("*.json"))[-45:]:
        try:
            records.append(json.loads(f.read_text()))
        except (ValueError, OSError):
            pass
    weekly_report = weekly(report, records)
    (DATA / "latest_weekly.json").write_text(json.dumps(weekly_report, indent=2, ensure_ascii=False, allow_nan=False) + "\n")
    print(f"Saved {DATA / 'latest_report.json'} and latest_weekly.json ({len(records)} snapshots)")
    print("Action:", report["decision"]["current_action"])
    return weekly_report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("live", "fixture"), default="live")
    parser.add_argument("--fixture", default="")
    args = parser.parse_args()
    if args.mode == "fixture":
        fixture = json.loads(Path(args.fixture).read_text())
        def fetch(url, params=None):
            k = next(k for k, v in URLS.items() if v == url)
            return fixture[k]
        report = collect(fetch=fetch)
    else:
        report = collect()
    save_report(report)


if __name__ == "__main__":
    main()