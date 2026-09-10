# What Does Not Staying in SUTD Hostel Cost You?

An offline data pipeline and static website that estimates the average weekday-morning public-transport commute from Singapore residential postal codes to the Singapore University of Technology and Design (SUTD).

The public site never calls Google Maps or OneMap. It reads generated JSON, so visitors do not need accounts, API credentials, or a backend.

## Current status

The repository is fully implemented and tested, with a three-row residential fixture for smoke tests. The production experiment intentionally has no destination coordinate yet: enter the exact SUTD latitude and longitude in [config/project.json](config/project.json). Add credentials to a local `.env` only when you are ready to collect routes.

## Methodology

The experiment definition is version-controlled in `config/project.json`.

- Google Maps: public transit, **arrive by** seven targets from 07:30 through 08:00 at five-minute intervals, across the ten weekdays 14–25 September 2026. That is 70 expected observations per postcode. Origins are batched into Google Routes API Compute Route Matrix requests, within the documented 100-element transit matrix limit.
- OneMap: public transport, **leave at** seven times from 06:20 through 06:50 at five-minute intervals, across the same ten weekdays. That is 70 expected observations per postcode.
- Provider averages use successful durations only. A provider needs at least 60 of 70 successful samples by default. The combined estimate is `(Google mean + OneMap mean) / 2`, and is produced only when both provider estimates meet the threshold.

These are intentionally different experiments. Google and OneMap use different routing systems and different time-query capabilities; the site shows both estimates instead of hiding disagreement.

See [docs/METHODOLOGY.md](docs/METHODOLOGY.md), [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md), and [docs/OPERATIONS.md](docs/OPERATIONS.md) for the detailed rationale and operating procedures.

## Setup

Requirements: Python 3.10+, `uv`, Node.js 20+, npm, and Git. On Windows, use `python3` if `python` points at an older installation.

```powershell
uv sync --extra dev
Copy-Item .env.example .env
```

Edit `config/project.json`:

```json
"destination": {
  "name": "Singapore University of Technology and Design",
  "latitude": 1.XXXX,
  "longitude": 103.XXXX
}
```

The two coordinates are the only project-specific product setting. Every provider receives exactly these coordinates.

For route collection, set:

```dotenv
GOOGLE_MAPS_API_KEY=...
ONEMAP_ACCESS_TOKEN=...
ONEMAP_EMAIL=...
ONEMAP_PASSWORD=...
```

The Google key is used only by local Python code. For OneMap, an existing `ONEMAP_ACCESS_TOKEN` is sufficient and takes priority. Email/password remain supported for automatic token acquisition/refresh, but are optional when a current token is supplied. OneMap's official authentication endpoint returns a token valid for three days; `.env` is ignored by Git.

## Address discovery

Address discovery is independent from routing. Import a source CSV with these columns:

`postal_code,address,latitude,longitude,residential_type,source,source_identifier,confidence`

The `confidence` value must be `VERIFIED`, `LIKELY`, `UNRESOLVED`, or `EXCLUDED`. Only `VERIFIED` and `LIKELY` are collected by default. A missing coordinate can be resolved with OneMap search:

```powershell
uv run python -m scripts.discover_addresses --input data/sample_residential_addresses.csv
uv run python -m scripts.discover_addresses --input path/to/hdb_residential.csv --source hdb
uv run python -m scripts.discover_addresses --input path/to/private_residential.csv --source private --resolve-missing
```

The source adapter preserves provenance and deduplicates by six-digit postal code in `data/residential_addresses.sqlite`. Do not brute-force all 000000–999999 values. Start with authoritative HDB/building sources, then add clearly identified private condominium/apartment/landed/mixed-use sources.

## Safe collection commands

The repository refuses an unscoped collection. `--limit` means residential origins, not observations; each origin has 70 jobs per provider.

```powershell
# Show workload; no API calls
uv run python -m scripts.collect_onemap --limit 10 --dry-run
uv run python -m scripts.collect_google --limit 10 --dry-run

# Small real runs
uv run python -m scripts.collect_onemap --limit 10
uv run python -m scripts.collect_google --limit 10

# One postcode
uv run python -m scripts.collect_onemap --postal-code 200640
uv run python -m scripts.collect_google --postal-code 200640

# Full runs. Google requires the explicit cost guard.
uv run python -m scripts.collect_onemap --all
uv run python -m scripts.collect_google --all --confirm-large-run
```

Google prints residential origins × 70 and an estimated matrix request count before starting. Successful and terminally failed observations are written immediately to SQLite. Restarting skips existing successes; failed rows can be retried. Ctrl+C is handled without discarding completed work.

## Build summaries and site

```powershell
uv run python -m scripts.build_summary
uv run python -m scripts.build_public_dataset
uv run python -m scripts.export_csv

Set-Location website
npm install
npm run dev
npm run build
```

The production artifacts are `website/data/commute-summary.json` and `website/data/methodology.json`. The browser ships compact summaries only; raw route observations remain in local SQLite and can be exported to CSV where provider licensing permits. The frontend never calls a paid API.

## Tests and validation

```powershell
uv run pytest
uv run ruff check .
Set-Location website
npm run build
```

Unit tests mock provider HTTP responses. Real provider calls are intentionally separate from the normal test suite; use the scoped collection commands above for explicit integration checks after configuring credentials.

## GitHub Pages

The repository includes `.github/workflows/pages.yml`. It builds only the already-generated static site and never needs API credentials. After pushing and enabling Pages in the repository settings:

1. Choose **GitHub Actions** as the Pages source.
2. Run the `Deploy static website to GitHub Pages` workflow (or push to `main`).
3. Open the Pages URL shown by GitHub.

Vite uses relative asset paths (`base: "./"`), so the site works at a repository subpath as well as at `/`. Regenerate `website/data/*.json`, commit the changed static dataset, and push whenever a collection is updated.

## Licensing and provider caveats

OneMap is Singapore Land Authority's authoritative national map and its APIs are subject to its API terms and quotas. Google Maps Platform data and route results are subject to Google's current Maps Platform Terms, billing, and storage/display restrictions. Keep raw provider-derived data local unless you have confirmed redistribution rights; publish the experiment definition and summaries only when permitted. See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
