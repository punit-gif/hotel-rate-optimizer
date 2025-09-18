# Architecture

```
+----------------+     +-----------+     +---------+     +---------+     +-----------+     +-----------+
| CSV / PMS Stub | --> |   ETL     | --> | Postgres| --> |   ML    | --> |  FastAPI  | --> | Streamlit |
+----------------+     +-----------+     +---------+     +---------+     +-----------+     +-----------+
                                                        |  (LGBM)  |
                                                        | fallback |
                                                        | Prophet  |
                                                        +----------+
                                                                   \
                                                                    \--> Notifier (SendGrid/SMTP @ 7:00 CST)
```
**Flow**

1. **ETL** loads `/sample_data/*.csv` and `/inbox/nightly.csv` (if present) and upserts into Postgres (UTC).
2. **ML** builds features, trains a LightGBM model (fallback: Prophet-style moving avg), and writes 14‑day forecasts to `forecasts` with recommended ADR via pricing rules.
3. **FastAPI** exposes auth, forecast query, brief generation/sending, and an ETL trigger endpoint.
4. **Streamlit** lets the GM login, view charts/tables, and send the Daily Rate Brief.
5. **Notifier** can run as a cron/APScheduler job to hit `/brief?send=true` daily at 07:00 America/Chicago.
