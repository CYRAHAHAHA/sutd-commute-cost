import "./style.css";

type EvidenceRecord = {
  source_postal_code: string;
  observation_mode: string;
  group_size: number | null;
  origin: [number, number] | null;
  observations: Array<[string, string, number | null, string, number, string | null, string | null]>;
};

type Evidence = {
  dataset_version: string;
  generated_at: string;
  provider: string;
  time_semantics: string;
  destination: { name: string; latitude: number | null; longitude: number | null };
  format: { observation_row: string[] };
  notes: string[];
  postcodes: Record<string, EvidenceRecord>;
};

const app = document.querySelector<HTMLDivElement>("#evidence-app")!;
document.documentElement.classList.add("methodology-document");
const dataUrl = (name: string) => new URL(`data/${name}`, document.baseURI).toString();
const formatDate = (value: string) => new Intl.DateTimeFormat("en-SG", { day: "numeric", month: "short", year: "numeric", timeZone: "Asia/Singapore" }).format(new Date(`${value}T00:00:00+08:00`));
const formatDuration = (seconds: number | null) => seconds === null ? "—" : `${Math.floor(seconds / 60)} min ${seconds % 60} sec`;
const formatCollectedAt = (value: string | null) => value ? new Intl.DateTimeFormat("en-SG", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Singapore" }).format(new Date(value)) : "—";

function providerLinks(postalCode: string, record: EvidenceRecord, evidence: Evidence): string {
  if (!record.origin || evidence.destination.latitude === null || evidence.destination.longitude === null) return "";
  const origin = `${record.origin[0]},${record.origin[1]}`;
  const destination = `${evidence.destination.latitude},${evidence.destination.longitude}`;
  const oneMapParams = new URLSearchParams({
    from: origin,
    fromname: `Postal code ${postalCode}`,
    to: destination,
    toname: evidence.destination.name.toUpperCase(),
  });
  const googleParams = new URLSearchParams({
    api: "1",
    origin,
    destination,
    travelmode: "transit",
  });
  return `
    <div class="provider-links">
      <div><span>OneMap</span><a href="https://www.onemap.gov.sg/routing?${oneMapParams.toString()}" target="_blank" rel="noopener noreferrer">Open this route planner ↗</a></div>
      <div><span>Google Maps</span><a href="https://www.google.com/maps/dir/?${googleParams.toString()}" target="_blank" rel="noopener noreferrer">Open Transit planner ↗</a></div>
    </div>
    <p class="provider-link-note">Both links use the same origin and SUTD destination coordinates as this dataset. Provider websites may recalculate with current timetable data; the table above is the historical record we collected.</p>`;
}

function emptyState(title: string, detail: string): string {
  return `<main class="failure-screen"><section class="failure-card"><div class="eyebrow">Evidence unavailable</div><h1>${title}</h1><p>${detail}</p><a class="methodology-button" href="./">← Back to lookup</a></section></main>`;
}

function render(postalCode: string, evidence: Evidence): void {
  const record = evidence.postcodes[postalCode];
  if (!record) {
    app.innerHTML = emptyState(`We don’t have ${postalCode} mapped.`, "Try a postcode from the static lookup first.");
    return;
  }
  const isRepresentative = record.observation_mode === "REPRESENTATIVE";
  const successful = record.observations.filter(row => row[3] === "SUCCESS").length;
  const observationRows = record.observations.length
    ? record.observations.map(([date, time, duration, status, attempts, collectedAt, errorCode]) => `
        <tr>
          <td>${formatDate(date)}</td>
          <td class="mono">${time}</td>
          <td class="duration">${formatDuration(duration)}</td>
          <td><span class="evidence-status ${status === "SUCCESS" ? "status-success" : "status-failed"}">${status === "SUCCESS" ? "SUCCESS" : errorCode || "FAILED"}</span></td>
          <td class="mono">${attempts}</td>
          <td>${formatCollectedAt(collectedAt)}</td>
        </tr>`).join("")
    : `<tr><td colspan="6" class="empty-table">No scheduled OneMap observations were persisted for this postcode.</td></tr>`;

  app.innerHTML = `
    <main class="evidence-page">
      <header class="topbar"><a class="brand" href="./"><span class="brand-dot"></span><span>SUTD commute cost</span></a><a class="methodology-button" href="./">← Back to lookup</a></header>
      <section class="evidence-hero">
        <div class="eyebrow">Evidence · OneMap</div>
        <h1>What was actually recorded for <span>${postalCode}</span>?</h1>
        <p class="lede">These are the persisted OneMap public-transport observations behind the postcode’s coverage estimate.</p>
        <div class="evidence-summary"><div><span>Successful readings</span><strong>${successful} / ${record.observations.length}</strong></div><div><span>Departure sample</span><strong>06:30 · 06:45 · 07:00</strong></div><div><span>Destination</span><strong>SUTD</strong><small>${evidence.destination.latitude}, ${evidence.destination.longitude}</small></div></div>
      </section>
      <section class="evidence-panel">
        <div class="evidence-panel-heading"><div><div class="section-label">Recorded route durations</div><h2>OneMap readings</h2></div><span class="dataset-tag">${evidence.dataset_version}</span></div>
        ${isRepresentative ? `<div class="callout"><strong>Development representative point</strong><span>This postcode inherits the persisted observations for representative postcode ${record.source_postal_code}. The same measured point is used for ${record.group_size ?? "the named development"} mapped postal points.</span></div>` : ""}
        ${record.origin ? `<p class="route-meta">Origin point used: <span class="mono">${record.origin[0]}, ${record.origin[1]}</span> · Destination: <span class="mono">${evidence.destination.latitude}, ${evidence.destination.longitude}</span></p>` : ""}
        ${providerLinks(postalCode, record, evidence)}
        <div class="evidence-table-wrap"><table><thead><tr><th>Service date</th><th>Leave home</th><th>OneMap total</th><th>Status</th><th>Attempts</th><th>Collected</th></tr></thead><tbody>${observationRows}</tbody></table></div>
        <p class="evidence-footnote">OneMap returns a total journey duration for the requested public-transport route. This project stores and shows that duration; it does not currently retain the provider’s individual bus/train legs, stop sequence, or raw response payload.</p>
      </section>
      <section class="evidence-explain"><div class="section-label">How to read this</div><h2>Evidence, without theatre.</h2><p>A successful row is one actual OneMap response persisted by the collector for this postcode/date/time job. Failed rows remain visible as failures and are never treated as zero minutes. The headline OneMap mean uses successful durations only and requires the configured minimum sample count.</p><p>Dataset generated: ${new Intl.DateTimeFormat("en-SG", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Singapore" }).format(new Date(evidence.generated_at))} Singapore time.</p></section>
      <footer><span>Want the full experiment definition?</span><a class="methodology-button" href="./methodology.html">Read methodology ↗</a></footer>
    </main>`;
}

const postalCode = new URLSearchParams(window.location.search).get("postal_code")?.trim() || "";
if (!/^\d{6}$/.test(postalCode)) {
  app.innerHTML = emptyState("Give us a six-digit postcode.", "The evidence page needs the postcode from a lookup result.");
} else {
  fetch(dataUrl("onemap-evidence.json"))
    .then(response => response.json() as Promise<Evidence>)
    .then(evidence => render(postalCode, evidence))
    .catch(() => { app.innerHTML = emptyState("The evidence file is missing.", "Rebuild the public dataset, then refresh this page."); });
}
