# Operations runbook

## First run

1. Set the SUTD coordinate in `config/project.json`.
2. Copy `.env.example` to `.env` and set provider credentials. `ONEMAP_ACCESS_TOKEN` alone is sufficient for OneMap; email/password are optional refresh credentials.
3. Import a reviewed residential source CSV, or build the HDB first-layer database with the resumable adapter.
4. Apply the direct-postal OneMap policy and mark landed homes out of scheduled routing.
5. Run both providers against `--limit 1` or `--limit 10` and inspect the SQLite rows.
6. Build the summary and static dataset.

```powershell
uv sync --extra dev
uv run python -m scripts.discover_addresses --input data/sample_residential_addresses.csv
uv run python -m scripts.import_hdb --dry-run
uv run python -m scripts.import_ura --dry-run
uv run python -m scripts.finalize_addresses --confirm-production
uv run python -m scripts.audit_addresses --require-complete --reject-fixtures
uv run python -m scripts.classify_onemap_groups --dry-run
uv run python -m scripts.classify_onemap_groups
uv run python -m scripts.collect_onemap --limit 1
uv run python -m scripts.collect_google --limit 1
uv run python -m scripts.build_public_dataset
```

## Google preflight

The dry run is intentionally non-billable and does not contact Google:

```powershell
uv run python -m scripts.collect_google --limit 10 --dry-run
```

With a small fixture this reports the selected origins, planned route elements, matrix requests, and current budget usage without contacting Google. The current direct-postal dry run reports 21,295 origins, 19,496 Google-eligible origins after the 3.5 km exclusion, 1,000 selected origins, 9,000 planned elements, and 108 matrix requests. The existing ledger contains 9,999 attempted events. That is a configuration and cost-safety check, not a live API credential check; the budget guard will refuse more work until the allowance is reviewed or reset.

After importing the real residential source, run the smallest live checks before a nationwide collection:

```powershell
uv run python -m scripts.collect_google --limit 1
uv run python -m scripts.collect_onemap --limit 1
```

The Google command makes 9 route elements across the configured three dates and arrival times (normally 9 matrix requests for one origin); OneMap makes 3 calls for one routed origin across the configured Monday date and three departure times. Inspect the persisted rows and provider statuses before starting the full runs. Do not treat a successful dry run alone as evidence that nationwide collection can proceed.

OneMap may validate a future date while still lacking a public-transport timetable for that date. The production configuration now uses only the fixed Monday date, which was confirmed routable during validation:

```powershell
uv run python -m scripts.collect_onemap --all --date 2026-09-14
```

The `--date` option only narrows the run to dates already configured for OneMap. It does not substitute dates. A route response containing only `WALK` legs is recorded as `NO_TRANSIT_ROUTE`, not as a long successful commute. Successful rows are skipped on later runs; failed or missing rows remain eligible for retry.

After each date-scoped run, audit the persisted rows before proceeding:

```powershell
uv run python -m scripts.audit_observations --provider ONEMAP
```

The audit checks the exact configured job keys, time semantics, destination coordinates, status/duration invariants, attempt counts, and collection metadata. Run it with `--require-complete` only after all configured dates for that provider have been collected. Extra rows from retained smoke tests are reported but do not replace missing production jobs.

## Duration estimates

Let `N` be the number of default-eligible residential origins (`VERIFIED` and `LIKELY`) after import, and let `S` be the number of eligible origins remaining after the Google radius exclusion. The exact nationwide runtime cannot be known until that database exists.

At the current configured pacing of four OneMap requests per second (240/minute, below the documented 300 calls/minute tokenized-API ceiling):

- OneMap requires `3 × R` route calls in the adopted one-date/three-time configuration, where `R` is the directly routed-origin count after landed-home exclusion. The current address database has `R = 21,295`, so the full workload is `63,885` route calls and the pacing-only lower bound is about 4 hours 26 minutes at four calls per second. The collector uses 16 workers, 32 in-flight jobs, and a single shared limiter at four requests per second to overlap normal request latency without multiplying provider traffic.
- A full OneMap run automatically performs a distributed preflight over 30 origins before the full workload. It refuses to continue when more than 20% of those observations fail, which catches date-specific timetable problems before tens of thousands of calls are spent. It also rejects walking-only responses, which prevents the API's walking fallback from becoming fake public-transport data. Review the failures and use `--skip-preflight` only when deliberately accepting that risk.
- Google requires `9 × S` route elements and `9 × ceil(S / 90)` matrix HTTP requests. At the default maximum `S = 1,000`, that is 9,000 elements and 108 matrix requests, or approximately 1 minute 48 seconds of pacing time before network latency and retries.

Illustrative OneMap pacing-only bounds are:

| Eligible origins | Route calls | Minimum pacing time |
| ---: | ---: | ---: |
| 100 | 300 | 1 min 15 sec |
| 500 | 1,500 | 6 min 15 sec |
| 1,000 | 3,000 | 12 min 30 sec |
| 5,000 | 15,000 | 1 h 2 min 30 sec |
| 10,000 | 30,000 | 2 h 5 min |

These are lower bounds, not promises: HTTP latency, 429 responses, transient failures, and exponential backoff add time. Google retries are also counted in the persistent budget ledger; the configured 9,000-event guard can stop a run before retries exceed the cap. In that case, already successful rows remain safe and the remaining work can be resumed only with available budget or an explicit `--override-budget` decision.

The live Google smoke tests used 18 ledger events. The completed 999-origin production sample required `--override-budget` because retries brought the ledger to 9,999 events. This remained one event below Google's currently listed 10,000-event free allowance, but leaves no practical headroom for additional Google calls in the current allowance period. Never delete or edit the usage ledger to hide smoke-test events; wait for the allowance reset or explicitly review billing before collecting more.

Address discovery/import is not included in the route estimates. Importing a reviewed CSV with coordinates is normally quick. The official HDB adapter performs one OneMap Search per explicit residential HDB property record; at the configured four requests per second, 10,796 current HDB candidates require a pacing-only lower bound of about 45 minutes. Its source-resolution checkpoint is committed per record, so it can be interrupted and resumed safely. Private residential coverage is imported locally from URA and does not consume OneMap geocoding calls.

For the HDB+URA production population, the adopted OneMap route collection is `21,295 × 3 = 63,885` route calls. Its pacing floor is about 4 hours 26 minutes at four calls per second, before retries. The repository does not start it as a side effect of address import or website build. Run the dry run immediately before launch and inspect the persisted rows before rebuilding the public dataset. Do not force a future date through `--skip-preflight` merely because the endpoint accepts its calendar value; that can store `NO_TRANSIT_ROUTE` observations and will not create timetable data that OneMap has not published yet.

OneMap access tokens are normally valid for three days. A fresh token covers the pacing floor for this reduced workload, but refresh it immediately before launch. The currently loaded token expires before the first experiment date and must be replaced before launch. If authentication fails, replace `ONEMAP_ACCESS_TOKEN` and rerun the same collector command; successful observations are skipped and only missing jobs are attempted. The collector stops immediately on authentication failure without converting the remaining jobs into terminal `FAILED` rows. Email/password refresh is supported when the account flow permits it, but do not assume it is unattended if an email confirmation code is required.

## Landed and unknown postcode fallback

The address index retains landed-home postcodes, but the scheduled OneMap population excludes them. Every HDB, EC, and private non-landed postcode is routed directly; no representative-development result is reused. The default GitHub Pages build displays landed homes as known-but-unmapped. The frontend has an optional build-time hook: copy `website/.env.example` to `website/.env` and set `VITE_LIVE_ROUTE_ENDPOINT` to a server-side proxy that accepts `POST {"postal_code":"123456"}` and returns the complete `PostcodeSummary` JSON shape. Do not put `ONEMAP_ACCESS_TOKEN`, `GOOGLE_MAPS_API_KEY`, or any provider credential in `website/.env`; the proxy, not browser JavaScript, owns credentials and quota controls.

## Parallelism and the one-day constraint

The official [OneMap routing endpoint](https://www.onemap.gov.sg/apidocs/routing) documents one `start` and one `end` coordinate per request. `numItineraries` controls how many alternatives one origin request returns; it is not a multi-origin batch facility. The routing documentation also lists HTTP 429 for quota exhaustion. OneMap's [current workshop material](https://www.onemap.gov.sg/apidocs/static/media/OneMap_API_Workshop_Presentation_260825.04f72136081dd249c5ee.pdf) states a 300-calls-per-minute limit for token-based APIs. The project therefore uses 16 internal workers and 32 in-flight jobs behind one aggregate limiter at four calls per second (240/minute), allowing more request overlap without exceeding the shared rate. Multiple terminal sessions with independent limiters would only create 429s; sharding remains useful for restartability or for an explicitly approved higher quota, not for bypassing the documented allowance.

For comparison, the original 70-observation design would require 6,603,380 calls. At the documented 300/minute ceiling, the theoretical minimum is about 15.3 days; completing it in 24 hours would require about 4,586 calls/minute. That is why the adopted configuration reduces temporal samples while retaining every origin.

The local feasibility analysis below is retained as historical context for the original 70-observation design. It is not the production policy: the current direct-postal configuration deliberately removes representative clustering for non-landed homes because nearby origins can still have different walking access and transit choices.

| Representative rule | Representatives after 3.5 km exclusion | Route calls | Minimum at 240/min | Minimum at 300/min |
| --- | ---: | ---: | ---: | ---: |
| No clustering | 86,309 | 6,041,630 | 17.5 d | 14.0 d |
| ≤30 m representative radius | 30,835 | 2,158,450 | 6.25 d | 5.0 d |
| ≤50 m representative radius | 18,399 | 1,287,930 | 3.73 d | 3.0 d |
| ≤100 m representative radius | 7,333 | 513,310 | 1.49 d | 1.19 d |
| ≤150 m representative radius | 4,036 | 282,520 | 0.82 d | 0.65 d |

This shows that 20–30 m clustering does not meet a one-day target under the original 70-observation design. The 100 m option is still slightly over a day even at 300/minute, while 150 m is coarse enough to risk assigning different walking access points or transit choices the same route. The adopted plan therefore keeps every origin and versions the one-date/three-time temporal reduction explicitly in `config/project.json`.

## Resuming

Collectors generate the same deterministic job keys every time. A `SUCCESS` row is skipped. A failed row is eligible to run again, and each new result is persisted immediately. The database uses a unique constraint to make retries idempotent.

Inspect progress with SQLite, for example:

```powershell
python -c "import sqlite3; c=sqlite3.connect('data/observations.sqlite'); print(c.execute(\"select provider,status,count(*) from commute_observation group by provider,status\").fetchall())"
```

## Rate limits and costs

Google transit matrices are batched, but every origin/arrival-time pair is still a billable route element according to the applicable Google pricing and quota plan. The default validation sample is at most 1,000 origins × 9 arrival observations = 9,000 planned events. Never omit `--confirm-large-run` from the Google full-run guard. The collector also refuses to exceed `GOOGLE_MONTHLY_REQUEST_BUDGET` unless `--override-budget` is explicit. OneMap calls are deliberately paced at four requests per second by default, below the documented 300 calls/minute tokenized-API ceiling; change the configured rate only after checking your account's current quota.

The configured 9,000-event budget is intentionally below Google's currently listed 10,000-event free usage cap for Compute Routes Essentials and Compute Route Matrix Essentials. This completed run used 9,999 events because retries are also counted. Check Google's [current pricing and billing page](https://developers.google.com/maps/billing-and-pricing/pricing) before another monthly run. A local SQLite usage ledger records every matrix element reserved before an HTTP attempt, including retries, so a restart cannot silently reset the safety count.

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

The normal public-dataset command verifies that every expected OneMap routed-origin job and every selected Google validation job has a persisted terminal row before writing website files. It also requires the configured minimum Google production sample (999 selected origins by default), preventing a small smoke test from being mistaken for the validation layer. A successful build writes `website/data/deployment-ready.json`, and the Pages workflow refuses to deploy without it. During an incomplete collection, use `uv run python -m scripts.build_public_dataset --allow-incomplete` only for a local preview; that mode removes the deployment marker and must never be deployed.

Commit the generated `website/data/` files, push `main`, and let the included Pages workflow deploy them. Deployment does not access provider APIs.

## Integration checks

Normal tests use mocked HTTP. With credentials and a configured destination, the smallest real checks are:

```powershell
uv run python -m scripts.collect_onemap --limit 1
uv run python -m scripts.collect_google --limit 1
```

Use `--dry-run` first. If credentials are unavailable, the unit suite, build, dataset generation, and website validation can still be completed; only these real provider calls remain external.
