import "./style.css";

type ProviderSpec = {
  time_semantics: string;
  times: string[];
  dates: string[];
  expected_samples: number;
  travel_mode: string;
};

type Methodology = {
  dataset_version: string;
  generated_at: string;
  timezone: string;
  collection_dates: string[];
  destination: { name: string; latitude: number | null; longitude: number | null };
  minimum_successful_samples: Record<string, number>;
  google_sampling: { exclusion_radius_km: number; sample_size: number; monthly_request_budget: number; sampling_seed: number; stratum_cell_degrees: number };
  providers: Record<string, ProviderSpec>;
};

type DeploymentReady = {
  dataset_version: string;
  verified_at: string;
  status: string;
  coverage: Record<string, { population: number; expected_jobs: number; persisted_jobs: number; missing_jobs: number }>;
};

const app = document.querySelector<HTMLDivElement>("#methodology-app")!;
document.documentElement.classList.add("dark-theme");
document.documentElement.classList.add("methodology-document");
const dataUrl = (name: string) => new URL(`data/${name}`, document.baseURI).toString();
const formatDate = (value: string) => new Intl.DateTimeFormat("en-SG", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Singapore" }).format(new Date(`${value}T00:00:00+08:00`));
const formatList = (values: string[]) => values.map(formatDate).join(" · ");
const number = (value: number) => new Intl.NumberFormat("en-SG").format(value);

function providerSection(name: string, spec: ProviderSpec, methodology: Methodology): string {
  const google = name === "GOOGLE";
  const label = google ? "Google Maps" : "OneMap";
  const role = google ? "validation layer" : "coverage layer";
  const semantics = google ? "ARRIVE BY" : "LEAVE AT";
  const dates = formatList(spec.dates);
  return `
    <section class="long-section" id="${name.toLowerCase()}">
      <div class="section-number">${google ? "02" : "03"}</div>
      <div>
        <div class="section-label">${role}</div>
        <h2>${label}: ${semantics.toLowerCase()}, deliberately.</h2>
        <p class="section-lede">${google ? "Google is used as an independent benchmark, not as an exhaustive map of every Singapore origin." : "OneMap is the national coverage layer for the residential points we can route safely."}</p>
        <div class="detail-table">
          <div><span>Time question</span><strong>${semantics} ${spec.times[0]}–${spec.times.at(-1)} Singapore time</strong></div>
          <div><span>Sampling dates</span><strong>${dates}</strong></div>
          <div><span>Expected readings</span><strong>${spec.expected_samples} per ${google ? "sampled postcode" : "routed origin"}</strong></div>
          <div><span>Travel mode</span><strong>${spec.travel_mode}</strong></div>
        </div>
        <p>${google ? `Each sampled origin is queried at ${spec.times.join(", ")}. The current sample is capped at ${number(methodology.google_sampling.sample_size)} origins, stratified geographically with a fixed seed. Origins at or within ${methodology.google_sampling.exclusion_radius_km.toFixed(1)} km of SUTD remain in the address dataset but are excluded from Google validation.` : "The current reduced experiment uses one routable weekday and three departure times. Named private non-landed developments share one deterministic representative point; landed homes remain in the address index but are excluded from scheduled mapping."}</p>
      </div>
    </section>`;
}

function render(methodology: Methodology, deployment: DeploymentReady): void {
  const google = methodology.providers.GOOGLE;
  const onemap = methodology.providers.ONEMAP;
  const onemapCoverage = deployment.coverage.ONEMAP;
  const googleCoverage = deployment.coverage.GOOGLE;
  app.innerHTML = `
    <main class="methodology-page">
      <header class="topbar"><a class="brand" href="./?theme=dark"><span class="brand-dot"></span><span>SUTD commute cost</span></a><a class="methodology-button" href="./?theme=dark">← Back to lookup</a></header>
      <section class="methodology-hero">
        <div class="eyebrow">Methodology · version ${methodology.dataset_version}</div>
        <h1>Every minute has a paper trail.</h1>
        <p class="lede">This page explains what the estimate means, where the observations come from, and where we intentionally refuse to pretend we know more than we measured.</p>
        <div class="study-stats"><div><span>Destination</span><strong>SUTD</strong><small>${methodology.destination.latitude}, ${methodology.destination.longitude}</small></div><div><span>Timezone</span><strong>${methodology.timezone}</strong><small>All query times are local</small></div><div><span>Dataset</span><strong>${deployment.status}</strong><small>${number(onemapCoverage.population)} OneMap origins · ${number(googleCoverage.population)} Google origins</small></div></div>
      </section>
      <nav class="methodology-nav" aria-label="Methodology sections"><a href="#question">01 · The question</a><a href="#google">02 · Google</a><a href="#onemap">03 · OneMap</a><a href="#calculation">04 · Calculation</a><a href="#limits">05 · Limits</a></nav>
      <div class="methodology-body">
        <section class="long-section" id="question">
          <div class="section-number">01</div>
          <div><div class="section-label">What this measures</div><h2>A weekday-morning commute estimate, not a promise.</h2><p class="section-lede">Enter a residential Singapore postal code and the site returns a precomputed estimate of the public-transport journey to the fixed SUTD destination.</p><p>The headline number is intended to answer a practical housing question: if you live here, how much weekday-morning travel time should you expect on the route sample we collected?</p><div class="callout"><strong>We do not route in the browser.</strong><span>The website reads static JSON generated from local SQLite observations. No account is required, no visitor postcode is stored, and no provider credential is shipped to GitHub Pages.</span></div><div class="detail-table"><div><span>Experiment dates</span><strong>${formatList(methodology.collection_dates)}</strong></div><div><span>Fixed destination</span><strong>${methodology.destination.name}<br />${methodology.destination.latitude}, ${methodology.destination.longitude}</strong></div><div><span>Minimum coverage</span><strong>${methodology.minimum_successful_samples.GOOGLE} / ${google.expected_samples} Google · ${methodology.minimum_successful_samples.ONEMAP} / ${onemap.expected_samples} OneMap</strong></div></div></div>
        </section>
        ${providerSection("GOOGLE", google, methodology)}
        ${providerSection("ONEMAP", onemap, methodology)}
        <section class="long-section" id="calculation">
          <div class="section-number">04</div>
          <div><div class="section-label">How we calculate</div><h2>Successful observations only.</h2><p class="section-lede">A failed route is missing data. It is never silently turned into zero minutes.</p><div class="formula-list"><div><span>Provider mean</span><strong>Arithmetic mean of successful duration values</strong></div><div><span>Provider status</span><strong>Valid only when the configured minimum sample count is met</strong></div><div><span>Combined estimate</span><strong>(Google mean + OneMap mean) / 2</strong></div></div><div class="callout caution"><strong>No return-trip arithmetic.</strong><span>The published estimate is one way, for the configured morning query. We did not collect return journeys, so the site does not multiply the number by two or claim a daily round-trip total.</span></div></div>
        </section>
        <section class="long-section" id="limits">
          <div class="section-number">05</div>
          <div><div class="section-label">Boundaries and safeguards</div><h2>Useful, transparent, a little humble.</h2><p class="section-lede">The route systems disagree sometimes. That is information, not a bug to hide.</p><div class="limit-grid"><div><h3>Resumable</h3><p>Each postcode/date/time/provider job has a unique key. Successful rows are skipped on restart; failures remain visible and retryable.</p></div><div><h3>Auditable</h3><p>Raw observations stay in local SQLite with status, duration, attempts, collection timestamp, and provider metadata.</p></div><div><h3>Budget-aware</h3><p>Google uses a capped stratified validation sample with an explicit request budget. Full runs require an operator confirmation flag.</p></div><div><h3>Licensing-aware</h3><p>The public site publishes derived summaries and the methodology. Raw provider route data remains local unless redistribution is permitted.</p></div></div><div class="detail-table"><div><span>OneMap dataset jobs</span><strong>${number(onemapCoverage.persisted_jobs)} / ${number(onemapCoverage.expected_jobs)} persisted · ${onemapCoverage.missing_jobs} missing</strong></div><div><span>Google validation jobs</span><strong>${number(googleCoverage.persisted_jobs)} / ${number(googleCoverage.expected_jobs)} persisted · ${googleCoverage.missing_jobs} missing</strong></div><div><span>Generated</span><strong>${new Date(deployment.verified_at).toLocaleString("en-SG", { timeZone: "Asia/Singapore" })} Singapore time</strong></div></div></div>
        </section>
      </div>
      <footer><span>Back to the lookup when you’re ready.</span><a class="methodology-button" href="./?theme=dark">Open calculator ↗</a></footer>
    </main>`;
}

Promise.all([
  fetch(dataUrl("methodology.json")).then(response => response.json() as Promise<Methodology>),
  fetch(dataUrl("deployment-ready.json")).then(response => response.json() as Promise<DeploymentReady>),
]).then(([methodology, deployment]) => render(methodology, deployment)).catch(() => {
  app.innerHTML = `<main class="failure-screen"><section class="failure-card"><div class="eyebrow">Methodology unavailable</div><h1>The paper trail is missing.</h1><p>Rebuild the static dataset and refresh this page.</p></section></main>`;
});
