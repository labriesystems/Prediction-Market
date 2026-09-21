# Belief Market

A play-money forecasting platform that measures what you believed **before** you saw the market, then tests whether you can turn that edge into profitable trades.

## The product loop

1. Enter a private probability for a question.
2. Unlock the crowd price only after committing your belief.
3. Buy YES or NO shares with play credits.
4. Resolve the question and score both forecasting and trading performance.
5. Compare calibration, Brier score, profit, and skill by domain.

This is not real-money gambling. Credits have no cash value.

## Run locally

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
flask --app app init-db
flask --app app seed
flask --app app run --debug
```

Open `http://127.0.0.1:5000`, choose a username, and enter the demo markets.

## Resolution

For V1, an administrator resolves questions. Set `ADMIN_KEY`, then visit `/admin` and enter that key. Every question should include a specific resolution rule and source.

## How scoring works

- **Brier score:** `(forecast - outcome)²`. Lower is better; 0 is perfect.
- **Calibration:** forecasts are grouped into probability bands and compared with actual outcome frequency.
- **Trading P&L:** contract settlement value minus credits spent.
- **Domain performance:** scores are split across categories such as music, technology, sports, and business.

## Market mechanism

The V1 automated market maker uses a logarithmic market scoring rule (LMSR). A YES share settles at 100 credits if YES occurs and 0 otherwise; NO behaves inversely. The displayed probability changes as users trade.

## Current limitations

- Username-only demo accounts; production needs real authentication.
- SQLite is appropriate for a prototype, not a high-traffic deployment.
- Admin resolution is centralized.
- No real money, deposits, withdrawals, or transferable credits.

