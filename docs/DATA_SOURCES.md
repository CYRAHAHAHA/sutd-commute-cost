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

The private-residential layer uses URA's official [No of Dwelling Units dataset](https://data.gov.sg/datasets/d_be71daeab5930f96b90ad2857454d876/view). Its GeoJSON contains a postal code, property type, project, and point coordinate for each private-residential dwelling-unit point. `scripts.import_ura` imports it locally without geocoding calls, marks it `VERIFIED`, and preserves HDB as the preferred record on a postal overlap. The source is refreshed outside Git in `data/input/URA_NoOfDwellingUnits.geojson`.

The resolver is configured at four OneMap Search calls per second (240/minute), below OneMap's documented tokenized API limit of 300 calls/minute. If SLA changes the account limit or the project receives a 429 response, lower the versioned setting before resuming.

OneMap Search is available as an optional coordinate resolver for rows without usable coordinates. A candidate whose residential classification is not authoritative should be marked `LIKELY`; unresolved or non-residential candidates must not enter the default route workload.

## Routing providers

The Google client calls `https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix` server-side with `X-Goog-Api-Key` and a narrow response field mask. The OneMap client uses `ONEMAP_ACCESS_TOKEN` directly when provided; otherwise it can authenticate against `/api/auth/post/getToken` using email/password, then calls `/api/public/routingsvc/route` with an `Authorization` token header.

Check the current provider terms, quota, and retention rules before redistributing raw route results. The public site publishes derived summaries plus a compact evidence index containing OneMap total durations and collection metadata; it does not publish raw provider response dumps or route-leg geometry. Keep the SQLite audit store and any full provider responses local unless redistribution is permitted. Do not place API keys, access tokens, raw provider response dumps, or credential-bearing logs in Git.
