# INDO-FOS — Frontend

Indian Ocean Forecasting & Observing System — the web client for
**SIH 2026 · PS26067** (Ministry of Earth Sciences / INCOIS).

Two audiences, one application:

- **Public mode** — a plain-language dashboard for citizens, fishers, students
  and coastal officials. Every number is a sentence first, and every sentence
  can be expanded to show the model value that produced it. English and हिन्दी.
- **Official mode** — the full technical console: observations, model
  verification, derived products, drift simulation, and the service catalogue.

---

## Run it

The backend must be running first.

```bash
# terminal 1 — API
cd backend
.venv/Scripts/python -m uvicorn app.main:app --reload

# terminal 2 — UI
cd frontend
npm install
npm run dev
```

Open **http://localhost:5173**. Vite proxies `/api` to `127.0.0.1:8000`, so the
browser sees one origin and the backend CORS allow-list stays tight.

```bash
npm run build        # production bundle -> dist/ (includes Cesium)
npm run typecheck    # tsc --noEmit
```

---

## Sections

Navigation is the router: `section` in the store decides what renders, so
every item in the sidebar is a place you can actually go.

| Section | Mode | What it is |
|---|---|---|
| **Ocean Today** | both | Plain-language assessment for one stretch of coast |
| **Live Map** | both | Cesium globe, layers, analysis overlays, time |
| **Observations** | official | The float / glider / CTD network, sortable, with profiles |
| **Model Accuracy** | official | Model against instruments, level by level and basin-wide |
| **Analysis** | official | Anomaly, eddies, mixed layer, thermocline, drift |
| **Data & Services** | official | Dataset metadata, REST surface, OGC WMS, palettes |
| **Reports** | both | A dated, printable situation report |
| **Settings** | both | Language, theme, text size, contrast, units |

---

## Turning model output into information

`src/lib/ocean-plain.ts` is the module that answers *so what?*

"27.4 °C" means nothing to a fisher in Kollam or to a joint secretary drafting
a note. "About 1.2 °C warmer than usual for this week, over roughly a tenth of
the Kerala coast, which pushes surface fish deeper" does.

Two rules hold throughout:

1. **Nothing is invented.** Every sentence derives from a value the backend
   returned, and the reader can always expand the card to see it. A missing
   value is stated as missing, never guessed.
2. **Thresholds are named constants with a stated basis** — `ANOMALY_WATCH_C`,
   `HEATWAVE_AREA_MODERATE`, `CURRENT_STRONG_MS` — because an operational
   service has to be able to defend where "moderate" ends and "high" begins.

Regional statistics are computed client-side over the loaded volume, so
choosing the Bay of Bengal recomputes the whole assessment against that
bounding box rather than re-reporting a basin-wide figure. Severity for
currents comes from the **mean** speed over the area, not the single fastest
cell: across a basin this size some cell is always fast, and a peak-driven
level would read "unusual" every day and therefore mean nothing.

Regions carry their own preposition (`phrase` / `phraseHi`) — "in the Bay of
Bengal", "off the Kerala coast", "around Lakshadweep" — because no single
preposition is right for a sea, a coastline and an island group at once.

---

## Why the field is quantised binary

`/fields/volume` returns an **OCVOL1** container: a uint8-quantised
`[time][depth][lat][lon]` block with a scale/offset pair, decoded by
`src/lib/ocvol.ts`. A 3-timestep × 13-level × 69 × 101 block is 0.26 MiB on
the wire against 1.0 MiB as float32.

The consequence that matters: **the whole volume sits in memory**, so changing
depth, stepping through time, or dragging the colour range repaints from the
existing typed array with **no network request**. That is what makes the
controls feel instant rather than laggy.

`renderPlaneToCanvas()` is the hot path — one pass over the plane, one LUT
lookup per cell, straight into an `ImageData`.

The backend caps a volume request at 60 timesteps, so a longer run comes back
subsampled. `volumeTimeIndex()` maps the UI's step onto the block's own axis;
without it the map draws a different day from the one the clock is showing.

---

## Colour scaling

The legend auto-fits to the **2nd–98th percentile** of the surface field
rather than the CF default range. This is not cosmetic: temperature's CF
default is 2–32 °C, but Indian Ocean surface water spans roughly 23–30 °C, so
the default spends three quarters of the ramp on values that are not present
and flattens every real gradient into one wash of orange.

Percentiles rather than min/max so a single anomalous cell cannot stretch the
scale. "Fit colours to this field" refits on demand; the reset control
restores the CF default.

---

## Accessibility

Not an afterthought — these decide whether the application is usable at all
for a large share of the people it serves.

- **15px base type**, not 13px, with a **text-size setting** (normal / large /
  very large) that scales the whole interface including the map controls.
  Browser zoom reflows the map badly and people do not know where the setting
  is.
- **Light theme by default.** A near-black console is unreadable on a
  projector in a bright room, which is where a public briefing happens. Dark
  is one click away for the 24×7 ops desk, and the Cesium scene follows the
  app theme rather than staying dark forever.
- **High-contrast mode** for glare and low vision.
- Colour never carries meaning alone: every severity is paired with an icon
  and a word.
- Skip link, landmarks, visible focus rings, 44px touch targets, `aria-sort`
  on sortable columns, `aria-live` on advisories, and full keyboard operation
  (`Space` plays, `←` `→` step through time).
- Devanagari gets its own font stack and looser leading at the same size.

---

## Deep — the ocean assistant

**Typed first, voice optional.** The previous version was voice-only, which is
the wrong default here: speech recognition on Indian-accented English is
unreliable, a boat and a control room are both noisy, and a shared desktop in
a district office may have no microphone. The microphone button appears only
when the browser actually supports recognition.

```
question → POST /agent/command  { transcript, screen snapshot, history }
         → { reply, actions[] }
         → applyActions() through the same store a click would use
```

`buildSnapshot()` in `src/lib/deep-client.ts` assembles what Deep can see:
variable, depth, timestep, colour range, layers, camera, alerts, and the open
collocation result. `applyAction()` routes every action through the same
zustand store, so there is one code path for state changes regardless of
origin. Unknown action types are ignored rather than thrown — a newer backend
must never break an older client mid-demo.

Suggestion chips come from the backend's own grammar, so what is offered is
always something Deep can really do.

> "what am I looking at?" · "show salinity" · "go to five hundred metres" ·
> "show me the eddies" · "where is the heatwave" · "fly to the Bay of Bengal"

---

## Structure

```
src/
├── App.tsx                    preferences, service discovery, routing
├── i18n/                      EN / HI strings and the useT() lookup
├── state/store.ts             shared UI state (zustand, persisted prefs)
├── ui/                        the component kit (Card, Stat, Table, …)
├── lib/
│   ├── ocean-plain.ts         model output -> sentences a reader can act on
│   ├── queries.ts             every server read, keyed once
│   ├── ocvol.ts               OCVOL1 decoder, plane rendering, percentiles
│   ├── grid-render.ts         JSON derived grids -> canvas overlays
│   ├── api.ts                 typed client for the REST surface
│   ├── cesium-setup.ts        offline viewer, no Ion token, themed scene
│   ├── particles.ts           current streamlines (screen-space overlay)
│   ├── alerts.ts              alerts derived from anomaly + eddy responses
│   ├── deep-client.ts         assistant snapshot, transport, action routing
│   └── format.ts              CF units -> symbols, coordinates, dates
├── components/
│   ├── AppShell.tsx           masthead, section navigation, status
│   ├── OceanMap.tsx           globe, field, overlays, markers, picking
│   ├── Timeline.tsx           playback (Space / arrow keys)
│   ├── ColourLegend.tsx       legend and range editor
│   ├── CollocationChart.tsx   observed vs model, difference shaded
│   ├── Assistant.tsx          Deep
│   ├── ErrorBoundary.tsx      last line of defence
│   └── Insignia.tsx           inline SVG marks
└── views/                     one file per section
```

Server data lives in React Query, never duplicated into the store, so there is
exactly one source of truth for anything fetched.

---

## Notes

- **Fully offline.** No Ion token, no CDN, no network imagery. Cesium's own
  Natural Earth II tileset is retoned per theme via imagery-layer brightness.
- **Streamlines are a screen-space overlay**, not a Cesium imagery layer.
  Particles are advected in geographic space and projected through the camera
  each frame; re-uploading an imagery layer every frame would be far more
  expensive. Trails come from fading the previous frame, so memory is flat
  regardless of trail length.
- **Alerts are derived, not hardcoded.** `deriveAlerts()` reads the anomaly
  grid and eddy census, so scrubbing through time changes the advisory list.
- **Click anywhere on the water to read its value.** Being able to ask "what
  is it here?" is the difference between a picture of the ocean and an
  instrument.
- **Projection morphs are guarded.** The morph is a tween advanced by render
  frames; a backgrounded tab throttles `requestAnimationFrame` and would leave
  the scene wedged in `SceneMode.MORPHING`, making the buttons look dead on
  return. A timer snaps it to the target if the animation has not landed.

### Superseded components

`src/components/legacy/` holds the previous interface — the layers rail,
profile panel, time scrubber, colorbar, analysis panel, globe view, the
voice-only Deep overlay, and six placeholder folders that were never wired to
the API. Nothing imports them and they are **excluded in `tsconfig.json`**.
Delete the directory when you are satisfied with the replacement.
