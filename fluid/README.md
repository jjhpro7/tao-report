# FLUID Investor Monitor v0.1

A separate monitoring pipeline for the **FLUID (formerly Instadapp)** token. Does not modify TAO's `latest_report.json`.

## Architecture

`CoinGecko(instadapp, BTC, ETH) + DefiLlama(combined, lending, dex; fees/revenue/holders-revenue; DEX volume) + Fluid Governance topic list` → `fluid/monitor.py` → `fluid/data/latest_report.json` + `fluid/data/latest_weekly.json` + dated history → GitHub raw JSON → GPT review.

**Critical distinctions**

1. CoinGecko token ID is `instadapp`, not `fluid`.
2. Combined Fluid TVL/revenue and child Lending/DEX figures **MUST NOT** be summed; child TVLs may overlap.
3. Fees paid by borrowers, protocol revenue and actual token-holder capture are not interchangeable.
4. `dailyHoldersRevenue` is a source-defined metric and is NOT proof of token buybacks or burns.
5. May 11, 2026 Resolv post-mortem **proposed** a pause on buybacks; current execution/restart status is *unverified* until independently established.
6. Governance headlines are alerts, not automatic proof of an executed vote, payment or on-chain action.
7. Missing or stale critical metrics block automated `ADD` calls. No price targets without locked empirical forecast model.

## Run locally

```sh
python3 -m unittest discover -s fluid/tests -v
python3 fluid/monitor.py --mode live
```

No third-party Python dependencies. GitHub workflow in `.github/workflows/fluid-monitor.yml` runs automatically around 08:30 in California; a manual **Run workflow** also works. Delayed GitHub schedules or source API failures are visible in `source_health`.

Optional: create repository Action secret `COINGECKO_DEMO_API_KEY` if public CoinGecko limits are hit. **Never commit secrets**.

## GPT source URLs (using `jjhpro7/tao-report` as temporary shared host)

- Daily: `https://raw.githubusercontent.com/jjhpro7/tao-report/main/fluid/data/latest_report.json`
- Weekly: `https://raw.githubusercontent.com/jjhpro7/tao-report/main/fluid/data/latest_weekly.json`

JSON will exist only after the workflow first successfully runs and commits it. The code must not fabricate sample data for a live report. For a separate `fluid-monitor` repo later, update the corresponding URLs after migration.

## v0.2 / unresolved verification

- Add independent active-loan / utilization data from Fluid native API (`api.fluid.instadapp.io`) after schema validation.
- Normalize competitive performance vs Aave, Morpho and Euler using matched measurements.
- Confirm current treasury assets EXCLUDING self-issued FLUID, unrecovered bad debt, payments for loss resolution, buyback transfers, and token burns with on-chain evidence.
- Trace actual governance decisions (executed proposals, not headlines) and monitor protocol incidents.
- Add liquidity/order-book, token exchange transfers, security alerting, locked monthly scenario vintages and out-of-sample backtests.
- Connect scheduled ChatGPT daily / weekly reports to the published JSON after source accuracy is validated and an automation slot is available.

## Definitions

- `HOLD_NO_ADD` = no objective ADD evidence; not a guarantee that risk is low.
- `REDUCE_REVIEW_REQUIRED` = review meaningful deteriorations; not an automatic order.
- `DATA_INSUFFICIENT` = essential sources absent or stale; no fresh investment advice.

**Primary data sources:** [Fluid Docs](https://docs.fluid.io/), [Governance](https://gov.fluid.io/latest), [DefiLlama Fluid](https://defillama.com/protocol/fluid), [CoinGecko FLUID](https://www.coingecko.com/en/coins/fluid), [DefiLlama SDK](https://github.com/DefiLlama/api-sdk).