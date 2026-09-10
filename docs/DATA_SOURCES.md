# Data sources and provenance

## Residential addresses

The importer accepts source CSVs so that each dataset can be reviewed and cited before use. Every row stores:

- six-digit postal code and normalized address;
- latitude/longitude used by both providers;
- residential type;
- source and source identifier;
- confidence and discovery timestamp.

The checked-in `data/sample_residential_addresses.csv` is a tiny fixture for pipeline validation, not a claim of nationwide completeness. For a production run, start from authoritative HDB residential building/property data and add adapters or preprocessed CSVs for private condominiums, apartments, landed homes, and mixed-use developments. Keep each source's terms and retrieval date alongside the downloaded source outside Git (`data/input/` is ignored).

OneMap Search is available as an optional coordinate resolver for rows without usable coordinates. A candidate whose residential classification is not authoritative should be marked `LIKELY`; unresolved or non-residential candidates must not enter the default route workload.

## Routing providers

The Google client calls `https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix` server-side with `X-Goog-Api-Key` and a narrow response field mask. The OneMap client authenticates against `/api/auth/post/getToken`, then calls `/api/public/routingsvc/route` with an `Authorization` token header.

Check the current provider terms, quota, and retention rules before redistributing raw route results. The project therefore keeps raw observations local by default and publishes only derived summaries plus the reproducible methodology. Do not place API keys, access tokens, raw provider response dumps, or credential-bearing logs in Git.
