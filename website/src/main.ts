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
  google: ProviderSummary;
  onemap: ProviderSummary;
  combined: { status: string; mean_seconds: number | null };
};

type Summary = {
  dataset_version: string;
  generated_at: string;
  minimum_successful_samples: number;
  postcodes: Record<string, PostcodeSummary>;
};

type Methodology = {
  dataset_version: string;
  generated_at: string;
  timezone: string;
  collection_dates: string[];
  destination: { name: string; latitude: number | null; longitude: number | null };
  minimum_successful_samples: number;
  providers: Record<string, { time_semantics: string; times: string[]; expected_samples: number; travel_mode: string }>;
};

const app = document.querySelector<HTMLDivElement>("#app")!;
const dataUrl = (name: string) => new URL(`data/${name}`, document.baseURI).toString();

const minutes = (seconds: number | null): string => seconds === null ? "—" : `${Math.round(seconds / 60)} min`;
const detailMinutes = (seconds: number | null): string => seconds === null ? "—" : `${(seconds / 60).toFixed(1)} min`;
const formatDate = (value: string) => new Intl.DateTimeFormat("en-SG", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Singapore" }).format(new Date(`${value}T00:00:00+08:00`));

function providerDetails(name: string, summary: ProviderSummary, methodology: Methodology): string {
  const spec = methodology.providers[name];
  const range = summary.min_seconds === null ? "—" : `${detailMinutes(summary.min_seconds)} – ${detailMinutes(summary.max_seconds)}`;
  return `
    <div class="provider-detail">
      <div class="detail-heading"><span>${name === "GOOGLE" ? "Google Maps" : "OneMap"}</span><span>${summary.successful_samples} / ${summary.expected_samples} successful</span></div>
      <div class="detail-grid">
        <span>Mean</span><strong>${detailMinutes(summary.mean_seconds)}</strong>
        <span>Median</span><strong>${detailMinutes(summary.median_seconds)}</strong>
        <span>Range</span><strong>${range}</strong>
      </div>
      <p>${name === "GOOGLE" ? "Arrive by" : "Leave home at"} ${spec.times[0]}–${spec.times.at(-1)} Singapore time, in five-minute steps.</p>
    </div>`;
}

function renderResult(record: PostcodeSummary, methodology: Methodology): string {
  const hasCombined = record.combined.status === "SUCCESS" && record.combined.mean_seconds !== null;
  const oneWay = hasCombined ? Math.round((record.combined.mean_seconds as number) / 60) : null;
  return `
    <section class="result-card" aria-live="polite">
      <div class="result-kicker">${hasCombined ? "Your estimate" : "Not enough observations yet"}</div>
      <div class="big-number">${minutes(record.combined.mean_seconds)}</div>
      <div class="result-label">Average weekday-morning<br />public-transport commute to SUTD</div>
      <div class="breakdown">
        <div><span>Google Maps</span><strong>${minutes(record.google.mean_seconds)}</strong></div>
        <div><span>OneMap</span><strong>${minutes(record.onemap.mean_seconds)}</strong></div>
        <div class="combined-row"><span>Combined</span><strong>${minutes(record.combined.mean_seconds)}</strong></div>
      </div>
      ${hasCombined ? `<p class="extrapolation">≈ ${oneWay! * 2} minutes commuting per school day<br /><span>≈ ${((oneWay! * 2 * 5) / 60).toFixed(1)} hours over a 5-day week</span><small>Simple round-trip extrapolation, not another route calculation.</small></p>` : `<p class="warning">This postcode is known, but both provider estimates need at least ${methodology.minimum_successful_samples} of ${record.google.expected_samples} successful samples before a combined estimate is shown.</p>`}
      <details class="methodology-detail">
        <summary>How was this calculated?</summary>
        ${providerDetails("GOOGLE", record.google, methodology)}
        ${providerDetails("ONEMAP", record.onemap, methodology)}
        <div class="provider-detail combined-detail"><div class="detail-heading"><span>Combined</span><span>equal weight</span></div><p>Combined = (Google mean + OneMap mean) / 2. Google and OneMap use different routing systems and different time-query capabilities, so their estimates may differ. Both are shown rather than hiding this disagreement.</p></div>
        <p class="note">The public build contains compact postcode summaries. Raw observations remain in the local SQLite databases and can be exported for inspection where provider licensing permits.</p>
      </details>
    </section>`;
}

function renderMethodology(methodology: Methodology): string {
  const google = methodology.providers.GOOGLE;
  const onemap = methodology.providers.ONEMAP;
  return `
    <section class="methodology-panel">
      <div class="section-eyebrow">The experiment</div>
      <h2>Transparent by design.</h2>
      <p>Every result is generated ahead of time. The website never calls a routing API and collects no visitor data.</p>
      <div class="methodology-columns">
        <div><h3>Google Maps</h3><p><strong>Arrive-by methodology.</strong> Seven arrival targets from ${google.times[0]} to ${google.times.at(-1)} at five-minute intervals, across ${methodology.collection_dates.length} weekdays. ${google.expected_samples} expected observations per postcode.</p></div>
        <div><h3>OneMap</h3><p><strong>Departure-time methodology.</strong> Seven departure times from ${onemap.times[0]} to ${onemap.times.at(-1)} at five-minute intervals, across the same weekdays. ${onemap.expected_samples} expected observations per postcode.</p></div>
      </div>
      <p class="dates">Collection dates: ${methodology.collection_dates.map(formatDate).join(" · ")}</p>
      <p class="fine-print">All times are Singapore Time (${methodology.timezone}). Minimum coverage: ${methodology.minimum_successful_samples} / 70 per provider. Dataset ${methodology.dataset_version}.</p>
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
  form.addEventListener("submit", (event) => {
    event.preventDefault();
    const postal = input.value.trim();
    if (!/^\d{6}$/.test(postal)) {
      message.textContent = "Enter exactly six digits.";
      message.className = "form-message error";
      result.innerHTML = "";
      return;
    }
    const record = summary.postcodes[postal];
    if (!record) {
      message.textContent = "That postcode is not in the residential dataset.";
      message.className = "form-message error";
      result.innerHTML = "";
      return;
    }
    message.textContent = "Found in the residential dataset.";
    message.className = "form-message success";
    result.innerHTML = renderResult(record, methodology);
    result.scrollIntoView({ behavior: "smooth", block: "start" });
  });
}

Promise.all([
  fetch(dataUrl("commute-summary.json")).then(response => response.json() as Promise<Summary>),
  fetch(dataUrl("methodology.json")).then(response => response.json() as Promise<Methodology>),
]).then(([summary, methodology]) => render(summary, methodology)).catch(() => {
  app.innerHTML = `<main><section class="hero"><div class="hero-copy"><div class="eyebrow">Dataset unavailable</div><h1>The static commute dataset could not be loaded.</h1><p class="lede">Run <code>uv run python -m scripts.build_public_dataset</code> and rebuild the website.</p></div></section></main>`;
});
