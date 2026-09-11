# Website design notes

## Product job

Help a prospective SUTD student answer one practical question quickly: “What will the weekday-morning commute from my postcode cost me in minutes?” The page is an operating surface, not a marketing landing page.

## Visual rules

- Calm paper background with deep green ink, a lime result accent, and a small coral action accent.
- One viewport, one primary action: enter a six-digit postcode and get the estimate.
- Keep the title useful and modest. The number and the lookup action have the strongest hierarchy.
- Use short labels, compact metadata, and plain-language states. Cheeky copy is allowed when it does not blur the methodology.
- Keep methodology available through a modal so transparency does not turn the main task into a scroll marathon.
- Preserve visible focus rings, labelled fields, keyboard-usable buttons, and clear invalid/missing-data states.

## Component vocabulary

- `topbar`: quiet product label and methodology entry point.
- `story`: one-sentence context and three trust cues.
- `lookup-card`: the primary input and result surface.
- `metric-grid`: OneMap coverage, Google validation, and equal-weight combined estimate.
- `methodology-dialog`: experiment semantics and selected-postcode evidence.

## Interaction constraints

- The document uses a fixed viewport layout with `overflow: hidden`; the methodology dialog may scroll internally on small screens.
- Results replace the empty state in the same card; they do not navigate or auto-scroll the user.
- The browser never calls a paid provider in the default static build.
