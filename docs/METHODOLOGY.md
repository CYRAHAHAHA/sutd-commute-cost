# Methodology

## Question

The site estimates the broad concept “average weekday-morning public-transport commute to SUTD” for a residential Singapore postal code. It does not claim that the two providers measure an identical route.

## Fixed experiment

The ten service dates are exactly:

`2026-09-14` through `2026-09-18`, and `2026-09-21` through `2026-09-25`.

All local times use `Asia/Singapore` (UTC+08:00). The source of truth is `config/project.json`; scripts derive jobs from it rather than carrying date constants.

## Google Maps

Google uses Routes API Compute Route Matrix with `travelMode=TRANSIT` and the configured SUTD coordinate as the sole destination. For each date, each arrival target is queried in batches of origins:

`07:30, 07:35, 07:40, 07:45, 07:50, 07:55, 08:00`

The request uses `arrivalTime` in RFC 3339 form. Transit matrices are limited to 100 route elements, so the implementation uses a conservative batch size of 90 origins and a single destination. A route matrix request produces one observation per origin for that arrival target.

## OneMap

OneMap uses the public transport routing endpoint with `routeType=pt`, `mode=TRANSIT`, `maxWalkDistance=1000`, and one itinerary. For each date, the query time is a home departure time:

`06:20, 06:25, 06:30, 06:35, 06:40, 06:45, 06:50`

OneMap expects dates as `MM-DD-YYYY` and times as `HH:MM:SS`. Its `route_summary.total_time` is stored as seconds.

## Statistics

Every expected job has a unique key: `(postal_code, provider, service_date, query_time)`. A successful provider mean is the arithmetic mean of successful `duration_seconds` values only. Failures are missing observations, never zero-minute values. The summary also records median, min, max, standard deviation, p10, p90, successful count, and expected count.

The default minimum is 60 / 70. Below that, the provider is marked `INSUFFICIENT_DATA` and its mean is not eligible for the combined estimate. Combined is exactly:

`(Google mean seconds + OneMap mean seconds) / 2`

It is not an average of all raw observations and is calculated only when both providers meet the minimum.

## Publication choice

The public dataset contains postcode summaries and methodology metadata. It intentionally does not ship all raw observations in the browser bundle: a nationwide 140-observation-per-postcode payload would be needlessly large and could create provider licensing issues. The local SQLite database is the audit store, and `scripts.export_csv` supports controlled exports.
