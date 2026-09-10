# Data sources and provenance

## Residential addresses

The importer accepts source CSVs so that each dataset can be reviewed and cited before use. Every row stores:

- six-digit postal code and normalized address;
- latitude/longitude used by both providers;
- residential type;
- source and source identifier;
- confidence and discovery timestamp.

The checked-in `data/sample_residential_addresses.csv` is a tiny fixture for pipeline validation, not a claim of nationwide completeness. For a production run, start from authoritative HDB residential building/property data and add adapters or preprocessed CSVs for private condominiums, apartments, landed homes, and mixed-use developments. Keep each source's terms and retrieval date alongside the downloaded source outside Git (`data/input/` is ignored).

The first concrete adapter is `scripts.import_hdb`. It consumes the official [HDB Property Information dataset](https://data.gov.sg/datasets/d_17f5382f26140b1fdae0ba2ef6239d2f/view) (`blk_no`, `street`, and the explicit `residential` flag), filters `residential=Y`, and resolves each exact block/street with OneMap Search. The OneMap result must match the source block and canonicalized street before its postal code and coordinate are accepted as `VERIFIED`. A SQLite `address_resolution` checkpoint is committed per source record, so an interrupted geocoding run resumes without repeating successful lookups. The official [HDB Existing Building GeoJSON](https://data.gov.sg/datasets/d_16b157c52ed637edd6ba1232e026258d/view) supplies postal candidates for the rare cases where a generic OneMap search returns a facility with `POSTAL=NIL` or a different same-number building; each candidate is still accepted only after OneMap verifies the block and street. It is not joined to the property table by block number alone because block numbers repeat across streets.

The downloaded HDB source files belong in ignored `data/input/`; record their retrieval date and the data.gov.sg dataset links in the operator notes. The [data.gov.sg download API](https://guide.data.gov.sg/developer-guide/dataset-apis/download-dataset) can be used to refresh them. HDB is not the same as all Singapore residences: private condominiums, apartments, landed homes, and mixed-use developments require additional source adapters before the project can claim complete national residential coverage.

OneMap Search is available as an optional coordinate resolver for rows without usable coordinates. A candidate whose residential classification is not authoritative should be marked `LIKELY`; unresolved or non-residential candidates must not enter the default route workload.

## Routing providers

The Google client calls `https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix` server-side with `X-Goog-Api-Key` and a narrow response field mask. The OneMap client uses `ONEMAP_ACCESS_TOKEN` directly when provided; otherwise it can authenticate against `/api/auth/post/getToken` using email/password, then calls `/api/public/routingsvc/route` with an `Authorization` token header.

Check the current provider terms, quota, and retention rules before redistributing raw route results. The project therefore keeps raw observations local by default and publishes only derived summaries plus the reproducible methodology. Do not place API keys, access tokens, raw provider response dumps, or credential-bearing logs in Git.
