import "./style.css";

type ProviderSummary = {
  status: string;
  mean_seconds: number | null;
  median_seconds: number | null;
  min_seconds: number | null;
  max_seconds: number | null;
  successful_samples: number;
  expected_samples: number;
};

type PostcodeSummary = {
  postal_code: string;
  latitude: number;
  longitude: number;
  distance_to_sutd_km: number | null;
  google_exclusion_reason: string | null;
  google_stratum: string | null;
  google_sample_selected: boolean;
  onemap_group_key: string | null;
  onemap_group_representative: string | null;
  onemap_group_size: number | null;
  onemap_observation_mode: string;
  onemap_exclusion_reason: string | null;
  google: ProviderSummary;
  onemap: ProviderSummary;
  combined: { status: string; mean_seconds: number | null };
};

type Summary = {
  dataset_version: string;
  generated_at: string;
  minimum_successful_samples: Record<string, number>;
  postcodes: Record<string, PostcodeSummary>;
};

type CompactSummary = {
  dataset_version: string;
  generated_at: string;
  minimum_successful_samples: Record<string, number>;
  postcodes: Array<[
    string, number, number,
    [string, number | null, number | null, number | null, number | null, number, number],
    [string, number | null, number | null, number | null, number | null, number, number],
    [string, number | null], string | null, number | null, string | null
  ]>;
};

type Methodology = {
  dataset_version: string;
  generated_at: string;
  timezone: string;
  collection_dates: string[];
  destination: { name: string; latitude: number | null; longitude: number | null };
  minimum_successful_samples: Record<string, number>;
  google_sampling: { exclusion_radius_km: number; sample_size: number; monthly_request_budget: number; sampling_seed: number; stratum_cell_degrees: number };
  providers: Record<string, { time_semantics: string; times: string[]; dates: string[]; expected_samples: number; travel_mode: string }>;
};

const app = document.querySelector<HTMLDivElement>("#app")!;
const dataUrl = (name: string) => new URL(`data/${name}`, document.baseURI).toString();
const liveRouteEndpoint = import.meta.env.VITE_LIVE_ROUTE_ENDPOINT?.trim() || null;

const minutes = (seconds: number | null): string => seconds === null ? "—" : `${Math.round(seconds / 60)} min`;
const detailMinutes = (seconds: number | null): string => seconds === null ? "—" : `${(seconds / 60).toFixed(1)} min`;
const formatDate = (value: string) => new Intl.DateTimeFormat("en-SG", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Singapore" }).format(new Date(`${value}T00:00:00+08:00`));

function decodeProvider(row: CompactSummary["postcodes"][number][3]): ProviderSummary {
  const [status, mean, median, min, max, successful_samples, expected_samples] = row;
  return {
    status: status === "S" ? "SUCCESS" : status === "X" ? "EXCLUDED" : "INSUFFICIENT_DATA",
    mean_seconds: mean,
    median_seconds: median,
    min_seconds: min,
    max_seconds: max,
    successful_samples,
    expected_samples,
  };
}

function decodeSummary(compact: CompactSummary): Summary {
  const postcodes: Record<string, PostcodeSummary> = {};
  for (const [postal_code, latitude, longitude, google, onemap, combined, representative, group_size, exclusion_code] of compact.postcodes) {
    postcodes[postal_code] = {
      postal_code,
      latitude,
      longitude,
      distance_to_sutd_km: null,
      google_exclusion_reason: google[0] === "X" ? "within_3.5km_of_sutd" : null,
      google_stratum: null,
      google_sample_selected: false,
      onemap_group_key: null,
      onemap_group_representative: representative,
      onemap_group_size: group_size,
      onemap_observation_mode: representative && representative !== postal_code ? "REPRESENTATIVE" : "DIRECT",
      onemap_exclusion_reason: exclusion_code === "L" ? "landed_home_excluded_from_scheduled_mapping" : null,
      google: decodeProvider(google),
      onemap: decodeProvider(onemap),
      combined: { status: combined[0] === "S" ? "SUCCESS" : "INSUFFICIENT_DATA", mean_seconds: combined[1] },
    };
  }
  return {
    dataset_version: compact.dataset_version,
    generated_at: compact.generated_at,
    minimum_successful_samples: compact.minimum_successful_samples,
    postcodes,
  };
}

function providerDetails(name: string, summary: ProviderSummary, methodology: Methodology, exclusionReason: string | null = null): string {
  const spec = methodology.providers[name];
  const range = summary.min_seconds === null ? "—" : `${detailMinutes(summary.min_seconds)} – ${detailMinutes(summary.max_seconds)}`;
  const exclusion = summary.status === "EXCLUDED"
    ? name === "GOOGLE" && exclusionReason === "within_3.5km_of_sutd"
      ? `<p class="warning">Google validation excludes this postcode because it is within the configured ${methodology.google_sampling.exclusion_radius_km.toFixed(1)} km SUTD radius.</p>`
      : `<p class="warning">${name === "GOOGLE" ? "Google validation excludes this retained landed-home record." : "OneMap scheduled coverage excludes this retained landed-home record."}</p>`
    : "";
  return `
    <div class="provider-detail">
      <div class="detail-heading"><span>${name === "GOOGLE" ? "Google Maps" : "OneMap"}</span><span>${summary.successful_samples} / ${summary.expected_samples} successful</span></div>
      <div class="detail-grid">
        <span>Mean</span><strong>${detailMinutes(summary.mean_seconds)}</strong>
        <span>Median</span><strong>${detailMinutes(summary.median_seconds)}</strong>
        <span>Range</span><strong>${range}</strong>
      </div>
      <p>${name === "GOOGLE" ? "Arrive by" : "Leave home at"} ${spec.times[0]}–${spec.times.at(-1)} Singapore time, in five-minute steps.</p>
      ${exclusion}
    </div>`;
}

function renderResult(record: PostcodeSummary, methodology: Methodology): string {
  const hasCombined = record.combined.status === "SUCCESS" && record.combined.mean_seconds !== null;
  const hasOneMap = record.onemap.status === "SUCCESS" && record.onemap.mean_seconds !== null;
  const primarySeconds = hasOneMap ? record.onemap.mean_seconds : hasCombined ? record.combined.mean_seconds : null;
  const oneWay = primarySeconds === null ? null : Math.round(primarySeconds / 60);
  const googleExcludedForRadius = record.google_exclusion_reason === "within_3.5km_of_sutd";
  const coverageWarning = record.onemap_exclusion_reason
    ? "This postcode is known, but landed homes are excluded from scheduled OneMap mapping."
    : googleExcludedForRadius
      ? `Google validation is intentionally excluded within ${methodology.google_sampling.exclusion_radius_km.toFixed(1)} km of SUTD. OneMap remains the coverage layer for this postcode.`
      : `This postcode is known, but OneMap needs at least ${methodology.minimum_successful_samples.ONEMAP} successful samples before a coverage estimate is shown.`;
  return `
    <section class="result-card" aria-live="polite">
      <div class="result-kicker">${hasCombined ? "Combined estimate" : hasOneMap ? "OneMap coverage estimate" : "Not enough observations yet"}</div>
      <div class="big-number">${minutes(primarySeconds)}</div>
      <div class="result-label">Average weekday-morning<br />public-transport commute to SUTD</div>
      <div class="breakdown">
        <div><span>Google Maps</span><strong>${minutes(record.google.mean_seconds)}</strong></div>
        <div><span>OneMap</span><strong>${minutes(record.onemap.mean_seconds)}</strong></div>
        <div class="combined-row"><span>Combined</span><strong>${minutes(record.combined.mean_seconds)}</strong></div>
      </div>
      ${primarySeconds !== null ? `<p class="extrapolation">≈ ${oneWay! * 2} minutes commuting per school day<br /><span>≈ ${((oneWay! * 2 * 5) / 60).toFixed(1)} hours over a 5-day week</span><small>Simple round-trip extrapolation of the displayed ${hasCombined ? "combined" : "OneMap"} estimate, not another route calculation.</small></p>` : `<p class="warning">${coverageWarning}</p>`}
      ${record.onemap_observation_mode === "REPRESENTATIVE" ? `<p class="note">OneMap uses the representative point for this named development (${record.onemap_group_representative}); the same measured route is assigned to its ${record.onemap_group_size} mapped postal points.</p>` : ""}
      ${record.onemap_exclusion_reason ? `<p class="warning">This residential record is retained in the address index, but landed homes are excluded from scheduled OneMap mapping. A live calculation is not enabled on this static site because provider credentials must not be shipped to the browser.</p>` : ""}
      <details class="methodology-detail">
        <summary>How was this calculated?</summary>
        ${providerDetails("GOOGLE", record.google, methodology, record.google_exclusion_reason)}
        ${providerDetails("ONEMAP", record.onemap, methodology)}
        <div class="provider-detail combined-detail"><div class="detail-heading"><span>Combined</span><span>equal weight</span></div><p>Combined = (Google mean + OneMap mean) / 2. Google and OneMap use different routing systems and different time-query capabilities, so their estimates may differ. Both are shown rather than hiding this disagreement.</p></div>
        <p class="note">The public build contains compact postcode summaries. Raw observations remain in the local SQLite databases and can be exported for inspection where provider licensing permits.</p>
      </details>
    </section>`;
}

function renderMethodology(methodology: Methodology): string {
  const google = methodology.providers.GOOGLE;
  const onemap = methodology.providers.ONEMAP;
  const googleTimes = google.times.join(", ");
  const onemapTimes = onemap.times.join(", ");
  return `
    <section class="methodology-panel">
      <div class="section-eyebrow">The experiment</div>
      <h2>Transparent by design.</h2>
      <p>Every result is generated ahead of time. The default site never calls a routing API and collects no visitor data. An optional live fallback can call a separately deployed server-side proxy.</p>
      <div class="methodology-columns">
        <div><h3>Google Maps</h3><p><strong>Validation layer.</strong> Arrival targets ${googleTimes}, across ${google.dates.length} weekdays. ${google.expected_samples} expected observations per sampled postcode. Origins within ${methodology.google_sampling.exclusion_radius_km.toFixed(1)} km of SUTD are retained but excluded from Google.</p></div>
        <div><h3>OneMap</h3><p><strong>Coverage layer.</strong> Departure sample ${onemapTimes}, across ${onemap.dates.length} weekdays. ${onemap.expected_samples} expected observations per postcode.</p></div>
      </div>
      <p class="dates">Collection dates: ${methodology.collection_dates.map(formatDate).join(" · ")}</p>
      <p class="fine-print">All times are Singapore Time (${methodology.timezone}). Minimum coverage: ${methodology.minimum_successful_samples.GOOGLE} / ${google.expected_samples} Google; ${methodology.minimum_successful_samples.ONEMAP} / ${onemap.expected_samples} OneMap. Dataset ${methodology.dataset_version}.</p>
    </section>`;
}

function render(summary: Summary, methodology: Methodology): void {
  app.innerHTML = `
    <main>
      <section class="hero">
        <div class="hero-copy">
          <div class="eyebrow">SUTD commute cost calculator</div>
          <h1>So you want to come to SUTD<br /><em>and don’t want to stay in hostel?</em></h1>
          <p class="lede">See what not staying in hostel costs you — in minutes.</p>
          <form id="lookup-form" class="lookup-form" novalidate>
            <label for="postal-code">Enter your postal code</label>
            <div class="input-row"><input id="postal-code" inputmode="numeric" maxlength="6" pattern="[0-9]{6}" placeholder="______" autocomplete="postal-code" /><button type="submit">See my commute</button></div>
            <p id="form-message" class="form-message">Six digits. No address data is sent anywhere.</p>
          </form>
        </div>
        <div class="hero-mark" aria-hidden="true"><span>07</span><span>30</span><small>arrive</small></div>
      </section>
      <div id="result"></div>
      ${renderMethodology(methodology)}
      <footer><span>What Does Not Staying in SUTD Hostel Cost You?</span><span>Static dataset · No accounts · No live routing</span></footer>
    </main>`;

  const form = document.querySelector<HTMLFormElement>("#lookup-form")!;
  const input = document.querySelector<HTMLInputElement>("#postal-code")!;
  const message = document.querySelector<HTMLParagraphElement>("#form-message")!;
  const result = document.querySelector<HTMLDivElement>("#result")!;
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const postal = input.value.trim();
    if (!/^\d{6}$/.test(postal)) {
      message.textContent = "Enter exactly six digits.";
      message.className = "form-message error";
      result.innerHTML = "";
      return;
    }
    let record = summary.postcodes[postal];
    const needsLiveLookup = !record || Boolean(record.onemap_exclusion_reason);
    if (needsLiveLookup && liveRouteEndpoint) {
      message.textContent = "Requesting a live estimate…";
      message.className = "form-message";
      try {
        const response = await fetch(liveRouteEndpoint, {
          method: "POST",
          headers: { "content-type": "application/json" },
          body: JSON.stringify({ postal_code: postal }),
        });
        if (!response.ok) throw new Error(`Live lookup failed: ${response.status}`);
        record = await response.json() as PostcodeSummary;
      } catch {
        message.textContent = "The live estimate could not be retrieved. Try again later.";
        message.className = "form-message error";
        result.innerHTML = "";
        return;
      }
    }
    if (!record) {
      message.textContent = liveRouteEndpoint
        ? "That postcode is not available from the live lookup service."
        : "That postcode is not precomputed. Live lookup is not enabled on this static site.";
      message.className = "form-message error";
      result.innerHTML = "";
      return;
    }
    message.textContent = liveRouteEndpoint && needsLiveLookup
      ? "Live estimate returned."
      : "Found in the residential dataset.";
    message.className = "form-message success";
    result.innerHTML = renderResult(record, methodology);
    result.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

Promise.all([
  fetch(dataUrl("commute-summary.json")).then(response => response.json() as Promise<CompactSummary>),
  fetch(dataUrl("methodology.json")).then(response => response.json() as Promise<Methodology>),
]).then(([summary, methodology]) => render(decodeSummary(summary), methodology)).catch(() => {
  app.innerHTML = `<main><section class="hero"><div class="hero-copy"><div class="eyebrow">Dataset unavailable</div><h1>The static commute dataset could not be loaded.</h1><p class="lede">Run <code>uv run python -m scripts.build_public_dataset</code> and rebuild the website.</p></div></section></main>`;
});
