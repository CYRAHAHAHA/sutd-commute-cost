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

function providerCopy(name: string, methodology: Methodology): string {
  const spec = methodology.providers[name];
  const label = name === "GOOGLE" ? "Google Maps" : "OneMap";
  const verb = name === "GOOGLE" ? "Arrive by" : "Leave home at";
  return `
    <div class="method-block">
      <div class="method-title"><h3>${label}</h3><span>${name === "GOOGLE" ? "validation" : "coverage"}</span></div>
      <p><strong>${verb} ${spec.times[0]}–${spec.times.at(-1)}</strong> Singapore time, across ${spec.dates.length} weekday${spec.dates.length === 1 ? "" : "s"}. That is ${spec.expected_samples} expected reading${spec.expected_samples === 1 ? "" : "s"} per postcode.</p>
    </div>`;
}

function selectedMethodology(record: PostcodeSummary, methodology: Methodology): string {
  const google = record.google;
  const onemap = record.onemap;
  const combined = record.combined;
  const googleNote = record.google_exclusion_reason === "within_3.5km_of_sutd"
    ? "Google validation is intentionally excluded inside the configured SUTD radius."
    : `${google.successful_samples} / ${google.expected_samples} Google readings succeeded.`;
  const oneMapNote = record.onemap_exclusion_reason
    ? "This retained landed-home record is outside scheduled OneMap coverage."
    : `${onemap.successful_samples} / ${onemap.expected_samples} OneMap readings succeeded.`;
  return `
    <div class="selected-method">
      <div class="selected-method-heading"><span>For ${record.postal_code}</span><span>${record.onemap_observation_mode === "REPRESENTATIVE" ? "development representative" : "mapped point"}</span></div>
      <div class="selected-stats">
        <div><span>Google mean</span><strong>${detailMinutes(google.mean_seconds)}</strong><small>${googleNote}</small></div>
        <div><span>OneMap mean</span><strong>${detailMinutes(onemap.mean_seconds)}</strong><small>${oneMapNote}</small></div>
        <div><span>Combined</span><strong>${detailMinutes(combined.mean_seconds)}</strong><small>${combined.status === "SUCCESS" ? "equal-weight provider mean" : `needs ${methodology.minimum_successful_samples.GOOGLE}/${google.expected_samples} Google and ${methodology.minimum_successful_samples.ONEMAP}/${onemap.expected_samples} OneMap readings`}</small></div>
      </div>
    </div>`;
}

function renderMethodology(methodology: Methodology): string {
  const google = methodology.providers.GOOGLE;
  const onemap = methodology.providers.ONEMAP;
  return `
    <dialog id="methodology-dialog" class="methodology-dialog" aria-labelledby="methodology-title">
      <div class="dialog-card">
        <div class="dialog-header">
          <div><div class="eyebrow">The small print, made useful</div><h2 id="methodology-title">How the number earns its keep.</h2></div>
          <button id="close-methodology" class="icon-button" type="button" aria-label="Close methodology">×</button>
        </div>
        <p class="dialog-intro">This is a static lookup. The browser does not call Google or OneMap, and nothing you type is sent anywhere.</p>
        <div id="selected-methodology"><p class="dialog-muted">Choose a postcode to see its provider breakdown here.</p></div>
        <div class="method-grid">
          ${providerCopy("GOOGLE", methodology)}
          ${providerCopy("ONEMAP", methodology)}
        </div>
        <div class="method-block formula-block"><div class="method-title"><h3>Combined</h3><span>50 / 50</span></div><p><strong>(Google mean + OneMap mean) / 2.</strong> They use different routing systems and different time-query semantics, so disagreement is shown—not quietly averaged away.</p></div>
        <div class="method-footer">${formatDate(google.dates[0])} · ${formatDate(google.dates.at(-1)!)} Google validation · ${formatDate(onemap.dates[0])} OneMap coverage · dataset ${methodology.dataset_version}</div>
      </div>
    </dialog>`;
}

function renderResult(record: PostcodeSummary, methodology: Methodology): string {
  const hasCombined = record.combined.status === "SUCCESS" && record.combined.mean_seconds !== null;
  const hasOneMap = record.onemap.status === "SUCCESS" && record.onemap.mean_seconds !== null;
  const primarySeconds = hasCombined ? record.combined.mean_seconds : hasOneMap ? record.onemap.mean_seconds : null;
  const oneWay = primarySeconds === null ? null : Math.round(primarySeconds / 60);
  const googleExcludedForRadius = record.google_exclusion_reason === "within_3.5km_of_sutd";
  const coverageWarning = record.onemap_exclusion_reason
    ? "Known postcode, but landed homes are not part of scheduled OneMap coverage."
    : googleExcludedForRadius
      ? `Google validation skips the configured ${methodology.google_sampling.exclusion_radius_km.toFixed(1)} km radius. OneMap remains the coverage layer.`
      : `OneMap needs at least ${methodology.minimum_successful_samples.ONEMAP} successful readings before it can estimate this postcode.`;
  return `
    <section class="result-card" aria-live="polite">
      <div class="result-topline"><span class="result-kicker">${hasCombined ? "The verdict" : hasOneMap ? "The coverage estimate" : "A small data snag"}</span><span class="result-postcode">${record.postal_code}</span></div>
      <div class="result-number">${minutes(primarySeconds)}</div>
      <div class="result-label">average weekday-morning commute to SUTD</div>
      <div class="metric-grid">
        <div class="metric"><span>OneMap</span><strong>${minutes(record.onemap.mean_seconds)}</strong><small>${record.onemap.successful_samples}/${record.onemap.expected_samples} successful</small></div>
        <div class="metric"><span>Google Maps</span><strong>${minutes(record.google.mean_seconds)}</strong><small>${record.google.successful_samples}/${record.google.expected_samples} successful</small></div>
        <div class="metric metric-accent"><span>Combined</span><strong>${minutes(record.combined.mean_seconds)}</strong><small>equal-weight mean</small></div>
      </div>
      ${primarySeconds !== null ? `<p class="extrapolation">≈ ${oneWay! * 2} minutes there-and-back on a school day <span>· ≈ ${((oneWay! * 2 * 5) / 60).toFixed(1)} h over five days</span></p>` : `<p class="warning">${coverageWarning}</p>`}
      ${record.onemap_observation_mode === "REPRESENTATIVE" ? `<p class="result-note">Named development representative: ${record.onemap_group_representative} · ${record.onemap_group_size} mapped postal points share this route.</p>` : ""}
      <button class="recipe-button open-methodology" type="button">How did you get that? <span>↗</span></button>
    </section>`;
}

function render(summary: Summary, methodology: Methodology): void {
  const google = methodology.providers.GOOGLE;
  const onemap = methodology.providers.ONEMAP;
  app.innerHTML = `
    <main>
      <header class="topbar">
        <div class="brand"><span class="brand-dot"></span><span>SUTD commute cost</span></div>
        <button id="open-methodology" class="methodology-button" type="button">How this works <span>↗</span></button>
      </header>
      <section class="workspace">
        <div class="story">
          <div class="eyebrow">A tiny piece of travel maths</div>
          <h1>Hostel is not the only way in.</h1>
          <p class="lede">Pop in a Singapore postal code. We’ll tell you what the commute asks for—in minutes, not vibes.</p>
          <div class="story-footnote"><span>precomputed</span><span>no accounts</span><span>no live routing</span></div>
        </div>
        <section class="lookup-card" aria-labelledby="lookup-title">
          <div class="card-spark" aria-hidden="true">✦</div>
          <div class="card-kicker">Your front door, roughly</div>
          <h2 id="lookup-title">Where are you starting from?</h2>
          <form id="lookup-form" class="lookup-form" novalidate>
            <label for="postal-code">Six-digit postal code</label>
            <div class="input-row"><input id="postal-code" inputmode="numeric" maxlength="6" pattern="[0-9]{6}" placeholder="050032" autocomplete="postal-code" aria-describedby="form-message" /><button type="submit">Show me <span>→</span></button></div>
            <p id="form-message" class="form-message">No address data is sent anywhere.</p>
          </form>
          <div id="result"><div class="empty-result"><strong>One postcode in. One useful answer out.</strong><span>Try <button id="sample-postcode" type="button" class="inline-button">050032</button> if you’d like a known good one.</span></div></div>
          <div class="card-footer"><span>${onemap.expected_samples} OneMap snapshots</span><span>${google.expected_samples} Google checks</span><span>SUTD-bound</span></div>
        </section>
      </section>
      <footer><span>What does not staying in SUTD hostel cost you?</span><span>Dataset ${summary.dataset_version}</span></footer>
    </main>
    ${renderMethodology(methodology)}`;

  const form = document.querySelector<HTMLFormElement>("#lookup-form")!;
  const input = document.querySelector<HTMLInputElement>("#postal-code")!;
  const message = document.querySelector<HTMLParagraphElement>("#form-message")!;
  const result = document.querySelector<HTMLDivElement>("#result")!;
  const dialog = document.querySelector<HTMLDialogElement>("#methodology-dialog")!;
  const selectedMethod = document.querySelector<HTMLDivElement>("#selected-methodology")!;

  const openMethodology = (record?: PostcodeSummary) => {
    selectedMethod.innerHTML = record ? selectedMethodology(record, methodology) : `<p class="dialog-muted">Choose a postcode to see its provider breakdown here.</p>`;
    if (typeof dialog.showModal === "function") dialog.showModal();
    else dialog.setAttribute("open", "");
  };

  document.querySelector<HTMLButtonElement>("#open-methodology")!.addEventListener("click", () => openMethodology());
  document.querySelector<HTMLButtonElement>("#close-methodology")!.addEventListener("click", () => dialog.close());
  dialog.addEventListener("click", (event) => { if (event.target === dialog) dialog.close(); });
  document.querySelector<HTMLButtonElement>("#sample-postcode")!.addEventListener("click", () => {
    input.value = "050032";
    input.focus();
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const postal = input.value.trim();
    if (!/^\d{6}$/.test(postal)) {
      message.textContent = "Six digits, please—the postcode is shy.";
      message.className = "form-message error";
      result.innerHTML = `<div class="empty-result empty-error"><strong>That one needs a tiny edit.</strong><span>Use exactly six numbers, including any leading zero.</span></div>`;
      return;
    }
    let record = summary.postcodes[postal];
    const needsLiveLookup = !record || Boolean(record.onemap_exclusion_reason);
    if (needsLiveLookup && liveRouteEndpoint) {
      message.textContent = "Asking the live fallback…";
      message.className = "form-message";
      try {
        const response = await fetch(liveRouteEndpoint, { method: "POST", headers: { "content-type": "application/json" }, body: JSON.stringify({ postal_code: postal }) });
        if (!response.ok) throw new Error(`Live lookup failed: ${response.status}`);
        record = await response.json() as PostcodeSummary;
      } catch {
        message.textContent = "The live estimate is having a day. Try again later.";
        message.className = "form-message error";
        result.innerHTML = `<div class="empty-result empty-error"><strong>No number yet.</strong><span>The live lookup could not return an estimate.</span></div>`;
        return;
      }
    }
    if (!record) {
      message.textContent = liveRouteEndpoint ? "That postcode is not available from the live lookup." : "That postcode is not in this precomputed map.";
      message.className = "form-message error";
      result.innerHTML = `<div class="empty-result empty-error"><strong>We don’t have that one mapped.</strong><span>Try another residential Singapore postcode.</span></div>`;
      return;
    }
    message.textContent = liveRouteEndpoint && needsLiveLookup ? "Live estimate returned." : "Found. No judgement about the journey length.";
    message.className = "form-message success";
    result.innerHTML = renderResult(record, methodology);
    document.querySelector<HTMLButtonElement>(".open-methodology")!.addEventListener("click", () => openMethodology(record));
  });
}

Promise.all([
  fetch(dataUrl("commute-summary.json")).then(response => response.json() as Promise<CompactSummary>),
  fetch(dataUrl("methodology.json")).then(response => response.json() as Promise<Methodology>),
]).then(([summary, methodology]) => render(decodeSummary(summary), methodology)).catch(() => {
  app.innerHTML = `<main class="failure-screen"><section class="failure-card"><div class="eyebrow">Dataset unavailable</div><h1>The commute map took a coffee break.</h1><p>Run <code>uv run python -m scripts.build_public_dataset</code>, then rebuild the website.</p></section></main>`;
});
