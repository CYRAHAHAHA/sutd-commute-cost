# Operations runbook

## First run

1. Set the SUTD coordinate in `config/project.json`.
2. Copy `.env.example` to `.env` and set provider credentials. `ONEMAP_ACCESS_TOKEN` alone is sufficient for OneMap; email/password are optional refresh credentials.
3. Import a reviewed residential source CSV.
4. Run both providers against `--limit 1` or `--limit 10` and inspect the SQLite rows.
5. Build the summary and static dataset.

```powershell
uv sync --extra dev
uv run python -m scripts.discover_addresses --input data/sample_residential_addresses.csv
uv run python -m scripts.collect_onemap --limit 1
uv run python -m scripts.collect_google --limit 1
uv run python -m scripts.build_public_dataset
```

## Google preflight

The dry run is intentionally non-billable and does not contact Google:

```powershell
uv run python -m scripts.collect_google --limit 10 --dry-run
```

With the current three-row fixture this reports 3 eligible origins, 27 planned route elements, 9 matrix HTTP requests, and 0 of the 9,000 configured Google budget events used. That is a successful local configuration and cost-safety check, but it is not a live API credential check.

After importing the real residential source, run the smallest live checks before a nationwide collection:

```powershell
uv run python -m scripts.collect_google --limit 1
uv run python -m scripts.collect_onemap --limit 1
```

The Google command makes 9 route elements across the configured three dates and arrival times (normally 9 matrix requests for one origin); OneMap makes 70 calls for one origin. Inspect the persisted rows and provider statuses before starting the full runs. Do not treat a successful dry run alone as evidence that nationwide collection can proceed.

## Resuming

Collectors generate the same deterministic job keys every time. A `SUCCESS` row is skipped. A failed row is eligible to run again, and each new result is persisted immediately. The database uses a unique constraint to make retries idempotent.

Inspect progress with SQLite, for example:

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/observations.sqlite'); print(c.execute(\"select provider,status,count(*) from commute_observation group by provider,status\").fetchall())"
```

## Rate limits and costs

Google transit matrices are batched, but every origin/arrival-time pair is still a billable route element according to the applicable Google pricing and quota plan. The default validation sample is at most 1,000 origins × 9 arrival observations = 9,000 planned events. Never omit `--confirm-large-run` from the Google full-run guard. The collector also refuses to exceed `GOOGLE_MONTHLY_REQUEST_BUDGET` unless `--override-budget` is explicit. OneMap calls are deliberately paced at one request per second by default; change the configured rate only after checking your account's current quota.

The default 9,000-event budget leaves 1,000 events below Google's currently listed 10,000-event free usage cap for Compute Routes Essentials and Compute Route Matrix Essentials. Check Google's [current pricing and billing page](https://developers.google.com/maps/billing-and-pricing/pricing) before a production run. A local SQLite usage ledger records every matrix element reserved before an HTTP attempt, including retries, so a restart cannot silently reset the safety count.

Retries use exponential backoff for transport errors, HTTP 408/425/429/5xx, and provider-declared transient errors. HTTP 429 is classified separately. Permanent invalid requests, authorization failures, not-found routes, and malformed responses become terminal `FAILED` observations instead of being retried forever.

## Rebuild and publish

After collection:

```powershell
uv run python -m scripts.build_summary
uv run python -m scripts.build_public_dataset
Set-Location website
npm ci
npm run build
```

Commit the generated `website/data/` files, push `main`, and let the included Pages workflow deploy them. Deployment does not access provider APIs.

## Integration checks

Normal tests use mocked HTTP. With credentials and a configured destination, the smallest real checks are:

```powershell
uv run python -m scripts.collect_onemap --limit 1
uv run python -m scripts.collect_google --limit 1
```

Use `--dry-run` first. If credentials are unavailable, the unit suite, build, dataset generation, and website validation can still be completed; only these real provider calls remain external.
