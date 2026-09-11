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

type BatchStatus = "MAPPED" | "INSUFFICIENT_DATA" | "LANDED_NOT_SCHEDULED" | "UNMAPPED" | "INVALID" | "EMPTY";

type BatchRow = {
  line: number;
  postal_code: string;
  record: PostcodeSummary | null;
  status: BatchStatus;
  note: string;
};

type ParsedBatchLine = {
  line: number;
  value: string;
  invalidReason?: string;
};

const BATCH_LIMIT = 2000;

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
document.documentElement.classList.add("dark-theme");
const dataUrl = (name: string) => new URL(`data/${name}`, document.baseURI).toString();
const liveRouteEndpoint = import.meta.env.VITE_LIVE_ROUTE_ENDPOINT?.trim() || null;

if ("serviceWorker" in navigator && import.meta.env.PROD) {
  window.addEventListener("load", () => {
    navigator.serviceWorker.register(new URL("./sw.js", document.baseURI), { scope: "./" }).catch(() => undefined);
  });
}

const minutes = (seconds: number | null): string => seconds === null ? "—" : `${Math.round(seconds / 60)} min`;
const wholeMinutes = (seconds: number | null): string => seconds === null ? "" : String(Math.round(seconds / 60));
const escapeHtml = (value: string): string => value.replace(/[&<>'"]/g, character => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", "'": "&#39;", '"': "&quot;" })[character] ?? character);

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

function primarySeconds(record: PostcodeSummary): number | null {
  if (record.combined.status === "SUCCESS" && record.combined.mean_seconds !== null) return record.combined.mean_seconds;
  if (record.onemap.status === "SUCCESS" && record.onemap.mean_seconds !== null) return record.onemap.mean_seconds;
  return null;
}

function parseBatchInput(text: string): ParsedBatchLine[] | string {
  const normalized = text.replace(/^\uFEFF/, "").replace(/\r\n?/g, "\n");
  const rawLines = normalized.split("\n");
  while (rawLines.length && rawLines.at(-1) === "") rawLines.pop();
  if (!rawLines.length) return "Paste at least one postal code to begin.";

  const first = rawLines[0].trim().toLowerCase().replace(/\s+/g, " ");
  const hasHeader = ["postal code", "postal_code", "postcode", "postal"].includes(first);
  const lines = hasHeader ? rawLines.slice(1) : rawLines;
  const lineOffset = hasHeader ? 2 : 1;
  if (!lines.length) return "That column only contains a header. Add at least one postal code.";
  if (lines.length > BATCH_LIMIT) return `Please paste no more than ${BATCH_LIMIT.toLocaleString("en-SG")} rows at a time.`;

  return lines.map((raw, index) => {
    const value = raw.trim();
    if (!value) return { line: index + lineOffset, value };
    if (raw.includes("\t")) return { line: index + lineOffset, value: "", invalidReason: "more than one column" };
    if (!/^\d{6}$/.test(value)) return { line: index + lineOffset, value: "", invalidReason: "not six digits" };
    return { line: index + lineOffset, value };
  });
}

function evaluateBatch(lines: ParsedBatchLine[], summary: Summary): BatchRow[] {
  return lines.map(line => {
    if (!line.value && !line.invalidReason) return { line: line.line, postal_code: "", record: null, status: "EMPTY", note: "blank row" };
    if (line.invalidReason) return { line: line.line, postal_code: "", record: null, status: "INVALID", note: line.invalidReason };
    const record = summary.postcodes[line.value];
    if (!record) return { line: line.line, postal_code: line.value, record: null, status: "UNMAPPED", note: "not in the static dataset" };
    if (record.onemap_exclusion_reason) return { line: line.line, postal_code: line.value, record, status: "LANDED_NOT_SCHEDULED", note: "landed homes are excluded from scheduled mapping" };
    if (record.onemap.status !== "SUCCESS" || record.onemap.mean_seconds === null) {
      return { line: line.line, postal_code: line.value, record, status: "INSUFFICIENT_DATA", note: "not enough successful OneMap readings" };
    }
    return { line: line.line, postal_code: line.value, record, status: "MAPPED", note: "static OneMap estimate" };
  });
}

function batchStatusLabel(status: BatchStatus): string {
  return status === "MAPPED" ? "MAPPED"
    : status === "LANDED_NOT_SCHEDULED" ? "LANDED · NOT SCHEDULED"
      : status === "INSUFFICIENT_DATA" ? "INCOMPLETE"
        : status;
}

function renderBatchTable(rows: BatchRow[]): string {
  return rows.map(row => {
    const record = row.record;
    const mappedPostal = row.postal_code || "—";
    const evidence = row.postal_code && record
      ? `<a class="batch-evidence" href="./evidence.html?postal_code=${encodeURIComponent(row.postal_code)}&theme=dark" target="_blank" rel="noopener noreferrer">Evidence ↗</a>`
      : "—";
    return `<tr class="batch-row-${row.status.toLowerCase()}">
      <td class="batch-line">${row.line}</td>
      <td class="mono">${escapeHtml(mappedPostal)}</td>
      <td class="batch-duration">${record ? wholeMinutes(record.onemap.mean_seconds) || "—" : "—"}</td>
      <td>${record ? wholeMinutes(record.google.mean_seconds) || "—" : "—"}</td>
      <td>${record ? wholeMinutes(record.combined.mean_seconds) || "—" : "—"}</td>
      <td><span class="batch-status">${batchStatusLabel(row.status)}</span></td>
      <td class="batch-note">${escapeHtml(row.note)}</td>
      <td>${evidence}</td>
    </tr>`;
  }).join("");
}

function batchClipboard(rows: BatchRow[], includePostalCode: boolean): string {
  const header = includePostalCode
    ? ["Postal code", "Estimate (min)", "Google (min)", "Combined (min)", "Status", "Note"]
    : ["Estimate (min)", "Google (min)", "Combined (min)", "Status", "Note"];
  const body = rows.map(row => {
    const cells = [
      ...(includePostalCode ? [row.postal_code] : []),
      row.record ? wholeMinutes(row.record.onemap.mean_seconds) : "",
      row.record ? wholeMinutes(row.record.google.mean_seconds) : "",
      row.record ? wholeMinutes(row.record.combined.mean_seconds) : "",
      batchStatusLabel(row.status),
      row.note,
    ];
    return cells.map(cell => cell.replace(/[\t\r\n]/g, " ")).join("\t");
  });
  return [header.join("\t"), ...body].join("\n");
}

async function copyText(text: string): Promise<void> {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(text);
    return;
  }
  const helper = document.createElement("textarea");
  helper.value = text;
  helper.setAttribute("readonly", "true");
  helper.style.position = "fixed";
  helper.style.opacity = "0";
  document.body.appendChild(helper);
  helper.select();
  if (!document.execCommand("copy")) throw new Error("Clipboard copy was not available");
  helper.remove();
}

function renderResult(record: PostcodeSummary, methodology: Methodology): string {
  const hasCombined = record.combined.status === "SUCCESS" && record.combined.mean_seconds !== null;
  const hasOneMap = record.onemap.status === "SUCCESS" && record.onemap.mean_seconds !== null;
  const estimateSeconds = primarySeconds(record);
  const oneWay = estimateSeconds === null ? null : Math.round(estimateSeconds / 60);
  const googleExcludedForRadius = record.google_exclusion_reason === "within_3.5km_of_sutd";
  const coverageWarning = record.onemap_exclusion_reason
    ? "Known postcode, but landed homes are not part of scheduled OneMap coverage."
    : googleExcludedForRadius
      ? `Google validation skips the configured ${methodology.google_sampling.exclusion_radius_km.toFixed(1)} km radius. OneMap remains the coverage layer.`
      : `OneMap needs at least ${methodology.minimum_successful_samples.ONEMAP} successful readings before it can estimate this postcode.`;
  return `
    <section class="result-card" aria-live="polite">
      <div class="result-topline"><span class="result-kicker">${hasCombined ? "The verdict" : hasOneMap ? "The coverage estimate" : "A small data snag"}</span><span class="result-postcode">${record.postal_code}</span></div>
      <div class="result-number">${minutes(estimateSeconds)}</div>
      <div class="result-label">average weekday-morning commute to SUTD</div>
      <div class="metric-grid">
        <div class="metric"><span>OneMap</span><strong>${minutes(record.onemap.mean_seconds)}</strong><small>${record.onemap.successful_samples}/${record.onemap.expected_samples} successful</small></div>
        <div class="metric"><span>Google Maps</span><strong>${minutes(record.google.mean_seconds)}</strong><small>${record.google.successful_samples}/${record.google.expected_samples} successful</small></div>
        <div class="metric metric-accent"><span>Combined</span><strong>${minutes(record.combined.mean_seconds)}</strong><small>equal-weight mean</small></div>
      </div>
      ${estimateSeconds !== null ? `<p class="extrapolation">≈ ${oneWay} minutes one way <span>· provider mean for the configured weekday-morning sample</span></p>` : `<p class="warning">${coverageWarning}</p>`}
      ${record.onemap_observation_mode === "REPRESENTATIVE" ? `<p class="result-note">Named development representative: ${record.onemap_group_representative} · ${record.onemap_group_size} mapped postal points share this route.</p>` : ""}
      <a class="evidence-button" href="./evidence.html?postal_code=${encodeURIComponent(record.postal_code)}&theme=dark" target="_blank" rel="noopener noreferrer">Ask for the evidence <span>↗</span></a>
    </section>`;
}

function render(summary: Summary, methodology: Methodology): void {
  const google = methodology.providers.GOOGLE;
  const onemap = methodology.providers.ONEMAP;
  app.innerHTML = `
    <main>
      <header class="topbar">
        <div class="brand"><span class="brand-dot"></span><span>SUTD commute cost</span></div>
        <a class="methodology-button" href="./methodology.html?theme=dark">How this works <span>↗</span></a>
      </header>
      <section class="workspace">
        <div class="story">
          <div class="eyebrow">SUTD commute lookup</div>
          <h1>One postcode, or a whole column.</h1>
          <p class="lede">Check a weekday-morning commute in seconds. Paste only postal codes; nothing else leaves this browser.</p>
          <div class="privacy-note" role="note"><span class="privacy-mark">✦</span><span><strong>Private by design.</strong> No user data is stored. No account or personal details needed—postal codes only.</span></div>
          <div class="story-footnote"><span>up to 2,000 rows</span><span>spreadsheet-ready</span><span>no live routing</span></div>
        </div>
        <section class="lookup-card" aria-labelledby="lookup-title">
          <div class="mode-switch" role="tablist" aria-label="Lookup mode">
            <button id="batch-mode" class="mode-tab is-active" type="button" role="tab" aria-selected="true" aria-controls="batch-panel">Paste a column</button>
            <button id="single-mode" class="mode-tab" type="button" role="tab" aria-selected="false" aria-controls="single-panel">Check one</button>
          </div>
          <div id="batch-panel" class="lookup-panel" role="tabpanel" aria-labelledby="batch-mode">
            <div class="card-kicker">For office lists and spreadsheets</div>
            <h2 id="lookup-title">Paste postal codes</h2>
            <p class="panel-intro">One six-digit code per line. No names, addresses, or other columns.</p>
            <label class="sr-only" for="batch-input">Postal-code column</label>
            <textarea id="batch-input" rows="7" spellcheck="false" placeholder="050032\n670501\n162009" aria-describedby="batch-help"></textarea>
            <div class="batch-guidance"><span>Example</span><code>050032 · 670501 · 162009</code><span>up to 2,000 rows</span></div>
            <div class="panel-actions"><button id="process-batch" class="primary-action" type="button">Check this column <span>→</span></button><button id="clear-batch" class="secondary-action" type="button">Clear</button></div>
            <p id="batch-help" class="form-message">Your input isn’t stored or sent anywhere. Results stay in this browser and can be copied straight into a sheet.</p>
            <div id="batch-results" class="batch-results" hidden>
              <div class="batch-result-topline"><div id="batch-summary" class="batch-summary" aria-live="polite"></div><button id="copy-output" class="copy-button" type="button">Copy results for spreadsheet</button></div>
              <div class="batch-secondary-actions"><button id="copy-full" class="inline-button" type="button">Copy complete table including postal codes</button></div>
              <div class="batch-table-wrap"><table><thead><tr><th>#</th><th>Postal code</th><th>Estimate</th><th>Google</th><th>Combined</th><th>Status</th><th>Note</th><th>Evidence</th></tr></thead><tbody id="batch-table"></tbody></table></div>
            </div>
          </div>
          <div id="single-panel" class="lookup-panel" role="tabpanel" aria-labelledby="single-mode" hidden>
            <div class="card-kicker">For a quick answer</div>
            <h2>Check one postcode</h2>
            <form id="lookup-form" class="lookup-form" novalidate>
              <label for="postal-code">Six-digit postal code</label>
              <div class="input-row"><input id="postal-code" inputmode="numeric" maxlength="6" pattern="[0-9]{6}" placeholder="050032" autocomplete="postal-code" aria-describedby="form-message" /><button type="submit">Show me <span>→</span></button></div>
              <p id="form-message" class="form-message">No address data is sent anywhere.</p>
            </form>
            <div id="result"><div class="empty-result"><strong>One postcode in. One useful answer out.</strong><span>Try <button id="sample-postcode" type="button" class="inline-button">050032</button> if you’d like a known good one.</span></div></div>
          </div>
          <div class="card-footer"><span>${onemap.expected_samples} OneMap snapshots</span><span>${google.expected_samples} Google checks</span><span>SUTD-bound</span></div>
        </section>
      </section>
      <footer><span>What does not staying in SUTD hostel cost you?</span><span>Dataset ${summary.dataset_version}</span></footer>
    </main>`;

  const batchTab = document.querySelector<HTMLButtonElement>("#batch-mode")!;
  const singleTab = document.querySelector<HTMLButtonElement>("#single-mode")!;
  const batchPanel = document.querySelector<HTMLDivElement>("#batch-panel")!;
  const singlePanel = document.querySelector<HTMLDivElement>("#single-panel")!;
  const activateMode = (mode: "batch" | "single") => {
    const batch = mode === "batch";
    batchTab.classList.toggle("is-active", batch);
    singleTab.classList.toggle("is-active", !batch);
    batchTab.setAttribute("aria-selected", String(batch));
    singleTab.setAttribute("aria-selected", String(!batch));
    batchPanel.hidden = !batch;
    singlePanel.hidden = batch;
  };
  batchTab.addEventListener("click", () => activateMode("batch"));
  singleTab.addEventListener("click", () => activateMode("single"));

  const batchInput = document.querySelector<HTMLTextAreaElement>("#batch-input")!;
  const batchMessage = document.querySelector<HTMLParagraphElement>("#batch-help")!;
  const batchResults = document.querySelector<HTMLDivElement>("#batch-results")!;
  const batchSummary = document.querySelector<HTMLDivElement>("#batch-summary")!;
  const batchTable = document.querySelector<HTMLTableSectionElement>("#batch-table")!;
  const copyOutputButton = document.querySelector<HTMLButtonElement>("#copy-output")!;
  const copyFullButton = document.querySelector<HTMLButtonElement>("#copy-full")!;
  let batchRows: BatchRow[] = [];
  const processBatch = () => {
    const parsed = parseBatchInput(batchInput.value);
    if (typeof parsed === "string") {
    batchMessage.textContent = parsed;
    batchMessage.className = "form-message error";
    batchResults.hidden = true;
    batchRows = [];
      document.querySelector("main")?.classList.remove("batch-active");
      return;
    }
    batchRows = evaluateBatch(parsed, summary);
    const mapped = batchRows.filter(row => row.status === "MAPPED").length;
    const unavailable = batchRows.length - mapped - batchRows.filter(row => row.status === "EMPTY").length;
    batchSummary.innerHTML = `<strong>${batchRows.length.toLocaleString("en-SG")} rows checked</strong><span>${mapped.toLocaleString("en-SG")} mapped · ${unavailable.toLocaleString("en-SG")} need attention</span>`;
    batchTable.innerHTML = renderBatchTable(batchRows);
    batchResults.hidden = false;
    document.querySelector("main")?.classList.add("batch-active");
    batchMessage.textContent = "Ready. Copy the results and paste them beside your original column.";
    batchMessage.className = "form-message success";
  };
  document.querySelector<HTMLButtonElement>("#process-batch")!.addEventListener("click", processBatch);
  document.querySelector<HTMLButtonElement>("#clear-batch")!.addEventListener("click", () => {
    batchInput.value = "";
    batchRows = [];
    batchResults.hidden = true;
    document.querySelector("main")?.classList.remove("batch-active");
    batchMessage.textContent = "Your input isn’t stored or sent anywhere. Results stay in this browser and can be copied straight into a sheet.";
    batchMessage.className = "form-message";
    batchInput.focus();
  });
  copyOutputButton.addEventListener("click", async () => {
    try {
      await copyText(batchClipboard(batchRows, false));
      copyOutputButton.textContent = "Copied ✓";
      window.setTimeout(() => { copyOutputButton.textContent = "Copy results for spreadsheet"; }, 1800);
    } catch {
      batchMessage.textContent = "Clipboard access was blocked. Select the table and copy it manually.";
      batchMessage.className = "form-message error";
    }
  });
  copyFullButton.addEventListener("click", async () => {
    try {
      await copyText(batchClipboard(batchRows, true));
      copyFullButton.textContent = "Complete table copied ✓";
      window.setTimeout(() => { copyFullButton.textContent = "Copy complete table including postal codes"; }, 1800);
    } catch {
      batchMessage.textContent = "Clipboard access was blocked. Select the table and copy it manually.";
      batchMessage.className = "form-message error";
    }
  });

  const form = document.querySelector<HTMLFormElement>("#lookup-form")!;
  const input = document.querySelector<HTMLInputElement>("#postal-code")!;
  const message = document.querySelector<HTMLParagraphElement>("#form-message")!;
  const result = document.querySelector<HTMLDivElement>("#result")!;
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
  });
}

Promise.all([
  fetch(dataUrl("commute-summary.json")).then(response => response.json() as Promise<CompactSummary>),
  fetch(dataUrl("methodology.json")).then(response => response.json() as Promise<Methodology>),
]).then(([summary, methodology]) => render(decodeSummary(summary), methodology)).catch(() => {
  app.innerHTML = `<main class="failure-screen"><section class="failure-card"><div class="eyebrow">Dataset unavailable</div><h1>The commute map took a coffee break.</h1><p>Run <code>uv run python -m scripts.build_public_dataset</code>, then rebuild the website.</p></section></main>`;
});
