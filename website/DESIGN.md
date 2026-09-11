# Website design notes

## Product job

Help a prospective SUTD student answer one practical question quickly: “What will the weekday-morning commute from my postcode cost me in minutes?” The page is an operating surface, not a marketing landing page.

## Visual rules

- High-contrast dark green background with near-white ink, a lime result accent, and a small coral action accent.
- One practical surface with two modes: paste a column for office workflows or enter one six-digit postcode for a quick estimate.
- Keep the title useful and modest. The number and the lookup action have the strongest hierarchy.
- Use short labels, compact metadata, and plain-language states. Cheeky copy is allowed when it does not blur the methodology.
- Keep the calculator single-screen; send detailed methodology to a dedicated reading page so transparency does not turn the main task into a scroll marathon.
- Preserve visible focus rings, labelled fields, keyboard-usable buttons, and clear invalid/missing-data states.

## Component vocabulary

- `topbar`: quiet product label and methodology entry point.
- `story`: one-sentence context and three trust cues.
- `lookup-card`: the primary input and result surface.
- `mode-switch`: the batch-column and single-postcode entry modes.
- `batch-table`: ordered, spreadsheet-ready results with explicit missing-data states.
- `metric-grid`: OneMap coverage, Google validation, and equal-weight combined estimate.
- `evidence-page`: the exact persisted OneMap duration observations for a selected postcode.
- `methodology-page`: the full experiment definition and its boundaries.

## Interaction constraints

- The desktop calculator uses a fixed viewport layout with `overflow: hidden`; below 820px it switches to a stacked, naturally scrollable layout so the form and results remain readable on phones. Methodology and evidence pages are scrollable reading views at every size.
- Results replace the empty state in the same card; they do not navigate or auto-scroll the user.
- The displayed duration is one way only. Do not multiply it by two or imply that a return journey was measured.
- The browser never calls a paid provider in the default static build.
- Batch processing is client-side only, preserves input order and duplicates, and caps a paste at 2,000 rows. Clipboard output is tab-separated for direct spreadsheet pasting; invalid or unavailable rows stay blank rather than becoming zero-minute results.
- The landing page is installable as a dark standalone PWA on supported mobile browsers. The app shell can open offline after its first visit; commute data uses network-first refresh so a stale dataset is not silently preferred when connectivity is available.
