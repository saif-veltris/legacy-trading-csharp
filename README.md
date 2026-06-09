# AlphaEdge Trading Engine v5.1
## Quantitative Strategies Division

**Internal Use Only — Not for Distribution**

---

### Overview

The AlphaEdge Trading Engine (AETE) is the core order management and risk system used by the
Quantitative Strategies Division for proprietary trading across US and European equity markets.
The system handles order routing, real-time risk evaluation, position tracking, and market data
ingestion for strategy portfolios managing approximately $50M NAV.

Current version: **5.1.3** (build 20170914)
Target framework: **.NET Framework 4.0** (upgrade to 4.5 planned for Q2 2018)
Visual Studio: **2010** (VS 2013 licenses requested, awaiting procurement)

---

### Architecture

```
AlphaEdge.Trading
├── Config/          AppSettings.cs          — all runtime configuration (constants)
├── DataAccess/      TradeRepository.cs      — trade/position persistence (ADO.NET)
│                    MarketDataRepository.cs — live price feeds (Bloomberg, Reuters)
├── Models/          Portfolio.cs            — portfolio and holding domain objects
├── Services/        OrderExecutionService.cs— FIX order routing to exchanges
│                    RiskEngine.cs           — real-time VaR and position limit checks
└── Utils/           CryptoHelper.cs         — encryption for sensitive payloads
```

---

### Build Instructions

1. Open `TradingEngine.sln` in Visual Studio 2010 or later.
2. Restore third-party DLLs from `\\fileserver\dev-deps\trading-engine\lib\` into `.\lib\`.
3. Select **Release | Any CPU** and build.
4. Deploy `bin\Release\AlphaEdge.TradingEngine.dll` to the app server per the ops runbook.

> **Note:** Do not run unit tests against PROD database. Set `IS_PRODUCTION = false` in
> `Config/AppSettings.cs` before running the test suite. Remember to revert before deploying.

---

### Configuration

All configuration is in `Config/AppSettings.cs` as compile-time constants. To change environment
(PROD vs UAT), comment/uncomment the relevant `#region` blocks and rebuild.

**Credential Rotation:** Contact DevOps via email to rotate DB/API credentials, then update the
constants in this file. Changes must be reviewed by the lead quant before merging to `trunk`.

---

### Known Issues / Open TODOs

| ID       | Description                                              | Open Since |
|----------|----------------------------------------------------------|------------|
| AE-441   | RiskEngine not thread-safe — multiple order threads race | 2013-03-12 |
| AE-612   | Move connection strings out of source to app.config      | 2012-07-05 |
| AE-772   | Portfolio constructor parameter order causes silent bugs  | 2014-11-20 |
| AE-890   | MarketDataRepository.GetHistoricalBars not implemented   | 2015-02-14 |
| AE-1004  | Upgrade DES encryption to AES-256                        | 2016-09-01 |
| AE-1101  | WebClient calls need timeout configuration               | 2017-01-30 |
| AE-1203  | SQL queries need parameterisation (flagged in sec audit) | 2015-08-10 |

---

### Contact

**Quant Dev Team:** quant-dev@alphaedge.internal
**Ops / Infra:**    trading-ops@alphaedge.internal
**On-call pager:**  ext. 4499 (6 AM – 8 PM ET, trading days only)

---

*Last updated: 2017-09-14 by R. Holloway (rholloway@alphaedge.internal)*
