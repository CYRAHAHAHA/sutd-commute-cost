# What Does Not Staying in SUTD Hostel Cost You?

An offline data pipeline and static website that estimates the average weekday-morning public-transport commute from Singapore residential postal codes to the Singapore University of Technology and Design (SUTD).

The public site never calls Google Maps or OneMap. It reads generated JSON, so visitors do not need accounts, API credentials, or a backend.

## Current status

The repository is fully implemented and tested, with a three-row residential fixture for smoke tests. The SUTD destination is configured in [config/project.json](config/project.json), and provider credentials belong only in the ignored local `.env`. The nationwide residential import and live route collection are still explicit operator steps.

## Methodology

The experiment definition is version-controlled in `config/project.json`.

- OneMap is the coverage layer: public transport, **leave at** seven times from 06:20 through 06:50 at five-minute intervals, across all ten weekdays 14–25 September 2026. That is 70 expected observations per eligible postcode.
- Google Maps is the validation layer: public transit, **arrive by** 07:30, 07:45, and 08:00 on the first experiment week's Monday/Wednesday/Friday (14, 16, and 18 September 2026). That is 9 expected observations per sampled postcode.
- The Google 9-observation design intentionally uses the first week's Monday/Wednesday/Friday; changing the configured Google date list automatically changes expected observations and budget calculations.
- The collector uses the normal Google Routes API service (`routes.googleapis.com`) and `ComputeRouteMatrix`, not Routes Preferred API. Google’s current reference supports `travelMode=TRANSIT` with `arrivalTime`; the implementation sends one fixed coordinate destination, a required response field mask, and batches conservatively below the 100-element transit limit.
- Residential origins within the configurable 3.5 km straight-line SUTD radius remain in the dataset but are marked `google_exclusion_reason=within_3.5km_of_sutd` and excluded from Google validation.
- Google samples up to 1,000 remaining origins using reproducible proportional geographic strata and a fixed seed: 1,000 × 9 = 9,000 planned billable events. A hard budget guard blocks additional Google events beyond the configured 9,000 unless `--override-budget` is explicit. Google currently lists a 10,000-event free usage cap for Compute Routes Essentials and Compute Route Matrix Essentials; verify the [current pricing page](https://developers.google.com/maps/billing-and-pricing/pricing) before each monthly run.
- Provider averages use successful durations only. A provider needs at least 8 / 9 Google or 60 / 70 OneMap successful samples. The combined estimate is `(Google mean + OneMap mean) / 2`, and is produced only when both provider estimates meet the threshold.

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

Google sampling controls are versioned in `config/project.json` and may be overridden locally in `.env`:

```dotenv
SUTD_EXCLUSION_RADIUS_KM=3.5
GOOGLE_SAMPLE_SIZE=1000
GOOGLE_MONTHLY_REQUEST_BUDGET=9000
GOOGLE_SAMPLING_SEED=20260910
```

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

For the official HDB starting population, download the current HDB Property Information CSV from data.gov.sg into `data/input/HDBPropertyInformation.csv`, then run the resumable OneMap resolver:

```powershell
uv run python -m scripts.import_hdb --dry-run
uv run python -m scripts.import_hdb --limit 10
uv run python -m scripts.import_hdb
```

The adapter filters the source's explicit `residential=Y` rows, searches OneMap using the exact block and street, verifies the returned block/street, and persists a checkpoint for every source record. It does not use an unsafe block-number-only join. HDB is the authoritative first layer; private residential sources still need separate reviewed adapters before claiming complete Singapore-wide coverage.

## Safe collection commands

The repository refuses an unscoped collection. For OneMap, `--limit` caps origins. For Google, `--limit` caps the reproducibly selected validation sample; the full eligible population is still used to allocate geographic strata. OneMap has 70 jobs per origin; Google has 9.

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

# Full runs. OneMap covers all eligible origins. Google selects at most 1,000.
uv run python -m scripts.collect_onemap --all
uv run python -m scripts.collect_google --all --confirm-large-run

# Only with an explicit decision to exceed the configured 9,000-event guard
uv run python -m scripts.collect_google --all --confirm-large-run --override-budget
```

Google prints the full population, radius exclusions, eligible count, selected count, planned route elements, matrix HTTP requests, and current budget usage before starting. Successful and terminally failed observations are written immediately to SQLite. Restarting skips existing successes; failed rows can be retried. Ctrl+C is handled without discarding completed work.

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

The Google dry run has been completed against the three-row fixture: 3 eligible origins, 27 planned route elements, 9 planned matrix requests, and 0 budget events used. This confirms local configuration, sampling, exclusion, resumability inputs, and budget accounting; it does not confirm live credentials because `--dry-run` makes no network calls.

## GitHub Pages

The repository includes `.github/workflows/pages.yml`. It builds only the already-generated static site and never needs API credentials. After pushing and enabling Pages in the repository settings:

1. Choose **GitHub Actions** as the Pages source.
2. Run the `Deploy static website to GitHub Pages` workflow (or push to `main`).
3. Open the Pages URL shown by GitHub.

Vite uses relative asset paths (`base: "./"`), so the site works at a repository subpath as well as at `/`. Regenerate `website/data/*.json`, commit the changed static dataset, and push whenever a collection is updated.

## Licensing and provider caveats

OneMap is Singapore Land Authority's authoritative national map and its APIs are subject to its API terms and quotas. Google Maps Platform data and route results are subject to Google's current Maps Platform Terms, billing, and storage/display restrictions. Keep raw provider-derived data local unless you have confirmed redistribution rights; publish the experiment definition and summaries only when permitted. See [docs/DATA_SOURCES.md](docs/DATA_SOURCES.md).
