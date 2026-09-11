# Methodology

## Question

The site estimates the broad concept “average weekday-morning public-transport commute to SUTD” for a residential Singapore postal code. It does not claim that the two providers measure an identical route.

## Fixed experiment

The ten service dates are exactly:

`2026-09-14` through `2026-09-18`, and `2026-09-21` through `2026-09-25`.

All local times use `Asia/Singapore` (UTC+08:00). The source of truth is `config/project.json`; scripts derive jobs from it rather than carrying date constants.

## OneMap coverage layer

OneMap uses the public transport routing endpoint with `routeType=pt`, `mode=TRANSIT`, `maxWalkDistance=1000`, and one itinerary. The production coverage sample uses this date and these departure times:

`2026-09-14 × 06:30, 06:45, 07:00`

This is a deliberate reduced temporal sample: one Monday with three representative departures spanning the original 06:20–06:50 window. It preserves every eligible residential postcode while reducing the OneMap workload to three observations per routed origin. It is not silently presented as the original 70-observation design; the provider-specific sampling definition is generated into the public methodology artifact. Google remains a separate validation layer with its own three-date, three-arrival-time sample.

OneMap expects dates as `MM-DD-YYYY` and times as `HH:MM:SS`. Its `route_summary.total_time` is stored as seconds.

The official routing contract validates a future date parameter, but it does not guarantee that the public-transport timetable for every future date is already available. Empirically, on 2026-09-11, the endpoint returned a normal transit itinerary for the configured 2026-09-14 date; tested later dates returned either `ROUTE_NOT_FOUND` or walking-only itineraries. The collector therefore requires a transit leg in the response and treats walking-only responses as `NO_TRANSIT_ROUTE`. The production experiment intentionally does not substitute those later dates: its OneMap date is fixed to 2026-09-14.

OneMap runs across every default-eligible HDB origin and every available named private non-landed/EC development representative. Private landed homes are retained as residential index records but excluded from scheduled mapping because one representative point for an estate or street would not be a defensible route origin. Named non-landed/EC developments are grouped by URA `PROJ_NAME`; the representative is the existing postcode point nearest the development's geographic medoid. Every member postcode remains searchable and inherits the representative's result with an explicit `REPRESENTATIVE` observation mode. Unnamed non-landed/EC points remain individual origins.

### Residential origin population

The production population combines two official layers. HDB Property Information rows with `residential=Y` are resolved from exact block/street searches through OneMap, checked against the returned block and canonicalized street, and stored as deduplicated postal-code points with source provenance. URA's No of Dwelling Units GeoJSON supplies private landed, non-landed, and executive-condominium postal points and coordinates directly. HDB remains the preferred record on an overlap. The HDB resolver checkpoints every source record in SQLite and can resume after interruption; the URA import is local and does not consume routing/geocoding quota. The resulting population is still limited to what these official completed-residential layers represent; any future source must be added as a separately identified adapter rather than silently mixed in.

The completed local source build contains 94,334 unique postal-code origins: 10,796 HDB records and 83,538 URA records. Three URA postal points overlap an HDB postal point and are retained under the HDB source, leaving 83,538 separate URA rows. The strict audit found zero duplicate postal keys and zero invalid coordinates. The current grouping pass identifies 7,255 named private non-landed/EC postal points in 2,545 developments, leaves 3,244 unnamed private non-landed/EC points individual, and excludes 73,039 private-landed points from scheduled OneMap routing. That produces 16,585 routed origins.

## Google validation layer

Google uses Routes API Compute Route Matrix with `travelMode=TRANSIT` and the configured SUTD coordinate as the sole destination. It samples these first-week weekdays and arrival targets:

`2026-09-14, 2026-09-16, 2026-09-18 × 07:30, 07:45, 08:00`

That is 9 observations per sampled origin. The request uses `arrivalTime` in RFC 3339 form. Transit matrices are limited to 100 route elements, so the implementation uses a conservative batch size of 90 origins and a single destination.

The implementation uses the standard Google Routes API service at `routes.googleapis.com`, specifically `ComputeRouteMatrix`, rather than Routes Preferred API. The request body sets `travelMode=TRANSIT`, `arrivalTime`, and the fixed SUTD latitude/longitude; the response field mask requests only origin index, destination index, status, condition, and duration. Google’s current [ComputeRouteMatrix reference](https://developers.google.com/maps/documentation/routes/reference/rest/v2/TopLevel/computeRouteMatrix) documents both `arrivalTime` for transit and the 100-element transit limit.

The 9-observation design deliberately uses only the first experiment week's Monday, Wednesday, and Friday. If the configured Google date list is expanded to include the second week, expected observations and the budget calculation expand automatically.

Google transit queries accept an arrival or departure timestamp only within the documented window of up to 7 days in the past or 100 days in the future relative to execution. The fixed September 2026 dates must therefore be collected during that window; the [transit route documentation](https://developers.google.com/maps/documentation/routes/transit-route) also cautions that transit predictions can change over time.

Before sampling, every scheduled-routing origin is annotated with its haversine distance to SUTD. Origins at or within `google_sampling.exclusion_radius_km` are retained in SQLite and public summaries with `google_exclusion_reason=within_3.5km_of_sutd` at the default radius, but receive no Google jobs. Landed homes already excluded from scheduled OneMap mapping are also excluded from the Google validation population, so the validation sample is drawn from locations that have a comparable OneMap result.

The remaining origins are grouped into fixed latitude/longitude grid cells. A Hamilton/largest-remainder allocation assigns sample quotas proportionally to cell population; a SHA-256 rank derived from the configured seed and postal code selects rows reproducibly inside each cell. The default is at most 1,000 sampled origins.

The Google budget guard counts attempted matrix elements from a persisted SQLite usage ledger and reserves every element before an HTTP attempt, including retries. The default planned budget is 9,000 events, leaving 1,000 events below Google's current 10,000-event Essentials free usage cap.

## Statistics

Every expected job has a unique key: `(postal_code, provider, service_date, query_time)`. A successful provider mean is the arithmetic mean of successful `duration_seconds` values only. Failures are missing observations, never zero-minute values. The summary also records median, min, max, standard deviation, p10, p90, successful count, and expected count.

The default minimum is 8 / 9 for Google and 2 / 3 for OneMap. Below its provider-specific threshold, a provider is marked `INSUFFICIENT_DATA` and its mean is not eligible for the combined estimate. Google-excluded rows are marked `EXCLUDED`. Combined is exactly:

`(Google mean seconds + OneMap mean seconds) / 2`

It is not an average of all raw observations and is calculated only when both providers meet the minimum.

## Publication choice

The public dataset contains postcode summaries, Google inclusion/exclusion metadata, methodology metadata, and a compact OneMap duration-evidence index. Every result links to a postcode-specific evidence page showing the persisted OneMap service date, departure time, total duration, status, attempts, and collection timestamp used for that coverage estimate. The evidence page also links to the OneMap and Google Maps route planners using the same stored origin and fixed SUTD destination coordinates. Those external pages may recalculate current timetable data; they are a way to inspect the queried locations, not a replay guarantee for the historical sample. The public dataset does not publish raw provider response payloads or individual bus/train leg geometry; the local SQLite database remains the full audit store, and `scripts.export_csv` supports controlled exports.

The displayed duration is one way only. Return journeys were not collected, so the site does not multiply a morning estimate by two or present a round-trip daily total.

## Unmapped and live lookup boundary

The static site can recognize retained landed-home postcodes, but it does not call OneMap or Google from browser JavaScript by default. A live fallback requires a server-side proxy with its own authentication, rate limiting, abuse protection, and provider-terms review. Until that proxy is separately deployed, an excluded landed record is shown as known-but-unmapped rather than being presented as a zero-minute or fabricated result.
