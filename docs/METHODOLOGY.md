# Methodology

## Question

The site estimates the broad concept “average weekday-morning public-transport commute to SUTD” for a residential Singapore postal code. It does not claim that the two providers measure an identical route.

## Fixed experiment

The ten service dates are exactly:

`2026-09-14` through `2026-09-18`, and `2026-09-21` through `2026-09-25`.

All local times use `Asia/Singapore` (UTC+08:00). The source of truth is `config/project.json`; scripts derive jobs from it rather than carrying date constants.

## OneMap coverage layer

OneMap uses the public transport routing endpoint with `routeType=pt`, `mode=TRANSIT`, `maxWalkDistance=1000`, and one itinerary. For each date, the query time is a home departure time:

`06:20, 06:25, 06:30, 06:35, 06:40, 06:45, 06:50`

OneMap expects dates as `MM-DD-YYYY` and times as `HH:MM:SS`. Its `route_summary.total_time` is stored as seconds.

OneMap runs across every default-eligible residential origin (`VERIFIED` and `LIKELY`) and is not limited by the Google budget guard.

## Google validation layer

Google uses Routes API Compute Route Matrix with `travelMode=TRANSIT` and the configured SUTD coordinate as the sole destination. It samples these first-week weekdays and arrival targets:

`2026-09-14, 2026-09-16, 2026-09-18 × 07:30, 07:45, 08:00`

That is 9 observations per sampled origin. The request uses `arrivalTime` in RFC 3339 form. Transit matrices are limited to 100 route elements, so the implementation uses a conservative batch size of 90 origins and a single destination.

The 9-observation design deliberately uses only the first experiment week's Monday, Wednesday, and Friday. If the configured Google date list is expanded to include the second week, expected observations and the budget calculation expand automatically.

Before sampling, every address is annotated with its haversine distance to SUTD. Origins at or within `google_sampling.exclusion_radius_km` are retained in SQLite and public summaries with `google_exclusion_reason=within_3.5km_of_sutd` at the default radius, but receive no Google jobs.

The remaining origins are grouped into fixed latitude/longitude grid cells. A Hamilton/largest-remainder allocation assigns sample quotas proportionally to cell population; a SHA-256 rank derived from the configured seed and postal code selects rows reproducibly inside each cell. The default is at most 1,000 sampled origins.

The Google budget guard counts attempted matrix elements from a persisted SQLite usage ledger and reserves every element before an HTTP attempt, including retries. The default planned budget is 9,000 events, leaving 1,000 events below Google's current 10,000-event Essentials free usage cap.

## Statistics

Every expected job has a unique key: `(postal_code, provider, service_date, query_time)`. A successful provider mean is the arithmetic mean of successful `duration_seconds` values only. Failures are missing observations, never zero-minute values. The summary also records median, min, max, standard deviation, p10, p90, successful count, and expected count.

The default minimum is 8 / 9 for Google and 60 / 70 for OneMap. Below its threshold, a provider is marked `INSUFFICIENT_DATA` and its mean is not eligible for the combined estimate. Google-excluded rows are marked `EXCLUDED`. Combined is exactly:

`(Google mean seconds + OneMap mean seconds) / 2`

It is not an average of all raw observations and is calculated only when both providers meet the minimum.

## Publication choice

The public dataset contains postcode summaries, Google inclusion/exclusion metadata, and methodology metadata. It intentionally does not ship raw observations in the browser bundle: the local SQLite database is the audit store, and `scripts.export_csv` supports controlled exports.
