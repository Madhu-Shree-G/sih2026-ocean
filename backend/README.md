# OceanView3D — Backend

Web-based interactive 3-D visualisation platform integrating numerical ocean
model output with in-situ observations.

**SIH 2026 · Problem Statement 26067** — Ministry of Earth Sciences / INCOIS

---

## What this service is for

The problem statement's stated pain is not "we have no 3-D viewer". It is that
operational oceanographers *"are forced to toggle between disparate software
packages, making it difficult to rapidly correlate model predictions with
observational evidence."*

So the centrepiece here is **collocation**: given an Argo float profile at
(lat, lon, time), extract the model's prediction at that same point, put both
on one depth axis, and quantify the difference.

```
GET /api/v1/collocation/profile/{id}?variable=temperature
```

Everything else — volumetric rendering, eddy detection, drift forecasting — is
built around making that comparison fast and legible.

---

## Quick start

```bash
cd backend
python -m venv .venv
.venv/Scripts/python -m pip install -r requirements.txt cmocean
.venv/Scripts/python scripts/generate_sample_data.py
.venv/Scripts/python -m uvicorn app.main:app --reload
```

On Windows PowerShell you can use the launcher instead:

```powershell
.\run.ps1 setup; .\run.ps1 data; .\run.ps1 serve
```

Then open **http://localhost:8000/docs**.

Verify the install:

```bash
.venv/Scripts/python -m pytest tests
.venv/Scripts/python scripts/smoke_test.py
```

`generate_sample_data.py` builds a physically plausible synthetic Indian Ocean
so the whole stack runs with **no network, no credentials, no downloads**. That
is deliberate: venue wifi fails, and a demo must not depend on it.

---

## Architecture

```
 Zarr store  ──┐                          ┌── /fields/volume    OCVOL1 binary → WebGL TEXTURE_3D
 (model, 4-D)  │                          ├── /fields/slice     binary | PNG | JSON
               ├── Catalog ── FastAPI ────┼── /collocation/*    model ↔ observation  ★
 SQLite/       │   (xarray)    + firewall ├── /derived/*        MLD, anomaly, eddies, drift
 PostGIS     ──┘                          ├── /wms              OGC WMS 1.3.0
 (profiles)                               └── /colormaps/*/lut  GPU palette swap
```

**Why quantised binary rather than JSON.** A 512×512×40 float32 cube is 42 MiB
*per variable per timestep*. Quantising to `uint8` with a scale/offset pair —
the mechanism CF already defines via `scale_factor`/`add_offset` — costs 8 bits
of precision a colour ramp cannot resolve anyway and drops that to 10 MiB. The
client uploads the payload straight into a WebGL2 `TEXTURE_3D` and reconstructs
physical values in the shader:

```glsl
value = offset + (raw - 1.0) * scale;   // raw == 0 means no data
```

Raw value `0` is reserved as the no-data sentinel so land and below-seafloor
cells are discarded in the fragment shader, leaving 255 usable levels.

The consequence that matters for the demo: **depth slicing, isosurface
thresholds and colorbar edits never touch the network.** They are shader
uniform changes. Dragging a colorbar recolours the Bay of Bengal at 60 fps.

### OCVOL1 wire format

| offset | size | content |
|--------|------|---------|
| 0 | 8 | magic `OCVOL1\x00\x00` |
| 8 | 4 | `uint32` LE header length *H* |
| 12 | *H* | UTF-8 JSON header |
| 12+*H* | *N* | `uint8` payload, C-order `[time][depth][lat][lon]` |

The JSON header carries `shape`, `scale`, `offset`, `value_range`, `bbox`,
`depths`, `times`, `nodata_raw` and the default colormap.

---

## Endpoints

37 endpoints. Full interactive reference at `/docs`.

### The core capability

| Endpoint | What it does |
|---|---|
| `GET /collocation/profile/{id}` | Observed profile + model prediction on one axis, with bias / RMSD / MAE / correlation |
| `GET /collocation/bias-map` | Every platform in view coloured by model−observation bias |
| `GET /collocation/variables` | Intersection of model variables and instrument variables |

### Fields

| Endpoint | Notes |
|---|---|
| `GET /fields/volume` | 4-D block as OCVOL1 binary |
| `GET /fields/slice` | One depth level — `binary`, `png` or `json` |
| `GET /fields/transect` | Draw a line, get the water column under it |
| `GET /fields/profile` | Model water column at a point |
| `GET /fields/timeseries` | One variable over time at a point |
| `GET /fields/hovmoller` | Depth against time at a point |

### Derived products

| Endpoint | Method |
|---|---|
| `GET /derived/mixed-layer-depth` | de Boyer Montégut (2004), 0.2 °C from a 10 m reference |
| `GET /derived/thermocline` | Depth of maximum \|dT/dz\| |
| `GET /derived/anomaly` | Field − climatology, with marine-heatwave cells flagged |
| `GET /derived/eddies` | Okubo–Weiss, cores at W < −0.2·σ(W) |
| `POST /derived/drift` | RK4 particle advection + diffusion → search radius |

### Catalog, colour, standards, admin

`/datasets`, `/datasets/plugins`, `/observations/*`, `/colormaps/*`,
`/wms` (GetCapabilities · GetMap · GetLegendGraphic · GetFeatureInfo),
`/admin/*`, `/health`, `/health/ready`, `/health/info`.

---

## Deep — the voice agent

`Deep` is a voice agent built into the console. It is aware of what is on
screen and can drive the interface by spoken command.

```
POST /api/v1/agent/command      utterance + screen snapshot -> reply + actions
GET  /api/v1/agent/capabilities wake words, intent set, LLM availability
GET  /api/v1/agent/health       readiness
```

### Two tiers, in order

1. **Grammar** (`app/agent/resolver.py`) — 27 intents, deterministic. Instant,
   offline, and structurally unable to invent an action that does not exist.
   On a demo stage that reliability is worth more than flexibility.
2. **Language model** (optional) — when the grammar cannot classify an
   utterance at all *and* `OCEANVIEW_ANTHROPIC_API_KEY` is set, Claude answers
   the open question using the screen snapshot as grounding.

The second tier **never emits actions directly**. It may propose a command
*phrase*, which is fed back through the grammar; only if the grammar
recognises it do the resulting actions run. Every action Deep takes is one the
grammar validated, whether a human or a model phrased it.

### Screen awareness

The client sends a `ScreenContext` with every utterance — current variable,
depth, timestep, colour range, active layers, camera, alerts, and the open
collocation result. Deep resolves relative commands ("go deeper", "next
frame") against it and grounds its answers in it:

> "For 2900044, the model is 0.11 degrees Celsius warmer than the float on
> average. RMSD 0.28. Correlation 1.00. The largest disagreement is 0.84
> degrees Celsius at 94 metres, which is the thermocline."

### Actions

Deep never mutates state itself. It returns declarative actions the client
applies — so every action is inspectable before it happens, and the client
keeps final authority over its own state. Vocabulary in
`app/agent/actions.py`: variable, depth, time, playback, layers, opacity,
exaggeration, colormap, colour range, analysis layer, selection, camera.

### What it understands

Variable and depth (`show salinity`, `go to five hundred metres`, `deeper`,
`surface`), time and playback (`play`, `next frame`, `go to the end`,
`faster`), layers (`turn off the currents`, `set currents to 50 percent`),
presentation (`use the balance palette`, `set range 22 to 30`, `fit to data`,
`vertical exaggeration thirty`), analysis (`show me the eddies`, `show the
bias map`, `show anomalies`), navigation (`fly to the Bay of Bengal`, `where
is the heatwave`, `reset the view`), and questions (`what am I looking at`,
`what is the bias`, `how many eddies`, `any alerts`).

Spoken numbers are parsed as words or digits, and the vocabulary includes
common mis-hearings — "sanity" resolves to salinity, because a demo should not
fail on a wobbly microphone.

---

## The firewall

Two halves. Middleware stops abusive **traffic**; validators stop abusive
**parameters**. For a gridded-data API the second matters more — the request
asking for a 200 GB hypercube is far more dangerous than the one that arrives
too often.

| Layer | Protection |
|---|---|
| `TrustedHostMiddleware` | Host allow-list (DNS rebinding) |
| `CORSMiddleware` | Explicit origin allow-list, never `*` with credentials |
| `SecurityHeadersMiddleware` | CSP, `nosniff`, `DENY`, Referrer-Policy, Permissions-Policy, HSTS in prod |
| `BodyLimitMiddleware` | 1 MiB body cap, 4 KiB query cap, handles chunked uploads without `Content-Length` |
| `RateLimitMiddleware` | Per-IP token bucket, separate heavy bucket, progressive cool-down |
| `ConcurrencyLimitMiddleware` | Caps simultaneous heavy requests |
| `guard_cell_budget` | Rejects oversized extractions before any array is materialised |
| `safe_identifier` | Strict allow-list on anything reaching a path or Zarr key |
| Exception handlers | One JSON envelope; tracebacks never reach the client |

Notes on the design:

- **`X-Forwarded-For` is only trusted in production**, where the service is
  known to sit behind a proxy. Trusting it by default would let any client
  spoof the header and bypass rate limiting entirely.
- **Admin routes fail closed.** With no `OCEANVIEW_ADMIN_API_KEY` set they are
  unusable rather than open.
- **Auto-stride over hard failure.** A whole-domain volume request is coarsened
  to fit the budget rather than 413'd, so the client still gets a usable field.
- Read endpoints are public by default, serving the public-outreach use case
  the problem statement asks for. Set `OCEANVIEW_REQUIRE_API_KEY=true` to gate
  them.

Configuration lives in `.env` — see `.env.example`.

---

## Extensibility

The problem statement calls out that existing tools cannot absorb a new
instrument *"without significant re-engineering"*. The answer is a narrow
interface plus a registry:

```python
from app.data.adapters.base import ObservationAdapter, ProfileRecord, registry

@registry.register
class ADCPAdapter(ObservationAdapter):
    name = "adcp_netcdf"
    suffixes = (".nc",)

    def read_profiles(self): ...
    def describe(self): ...
```

Drop the file into `app/data/adapters/` and it appears at
`GET /api/v1/datasets/plugins` — no change to the API layer. Third-party
packages can register through the `oceanview.adapters` entry-point group
without forking.

Shipped adapters: `netcdf_model` (CMEMS/HYCOM/ROMS/INDOFOS), `argo_netcdf`
(Argo GDAC format), `csv_profile` (CTD and mooring text exports).

---

## Loading real data

```bash
# What would an adapter make of this file?
python scripts/ingest.py inspect path/to/file.nc

# Gridded model output → chunked Zarr store
python scripts/ingest.py model glorys.nc --id glorys_ao --bbox 55,-10,100,26

# In-situ profiles → database (idempotent; re-runs skip existing cycles)
python scripts/ingest.py observations argo_dir/ --pattern "*.nc"

# Pick it up without a restart
curl -X POST -H "X-Admin-Key: $OCEANVIEW_ADMIN_API_KEY" \
     http://localhost:8000/api/v1/admin/catalog/reload
```

| Source | Where | Registration |
|---|---|---|
| CMEMS GLORYS / Analysis-Forecast | marine.copernicus.eu | yes |
| HYCOM GOFS 3.1 | open OPeNDAP | **no** — easiest start |
| Argo GDAC | data-argo.ifremer.fr | no |
| INCOIS ERDDAP / LAS | incois.gov.in | varies |
| World Ocean Atlas 2023 | NOAA NCEI | no — climatology for anomalies |
| GEBCO 2024 | gebco.net | no — bathymetry |

---

## The demo dataset

`scripts/generate_sample_data.py` produces a 145 × 181 × 25 × 15 grid
(0.25°, 25 levels to 2000 m, 15 daily steps) over 55–100°E, 10°S–26°N, plus 654
in-situ profiles from 70 Argo floats, 6 gliders and 40 CTD casts.

Validated against real Indian Ocean values:

| Quantity | Generated | Reality |
|---|---|---|
| SST, equator | 29.4 °C | ~29 °C |
| SST, N Arabian Sea | 24.3 °C | 22–25 °C (winter) |
| T at 200 m, equator | 11.4 °C | ~13 °C |
| T at 2000 m | 3.0 °C | 2–3 °C |
| Surface salinity, Bay of Bengal | 32.0 psu | 31–33 psu |
| Surface salinity, Arabian Sea | 36.6 psu | 36–37 psu |
| Surface current speed | 0.14 mean / 1.27 max m/s | realistic |

Embedded features to demo against:

- **26 mesoscale eddies** drifting westward through the run
- **A tropical cyclone cold wake** crossing the Bay of Bengal from the midpoint
- **A marine heatwave** intensifying in the eastern Arabian Sea (~68.5°E,
  14.5°N) — absent at `time_index=0`, clearly flagged by the final step
- Somali and Oman monsoon upwelling; Bay of Bengal freshwater cap

Observations are **not** the model plus white noise. Each platform carries a
small persistent offset, and the synthetic ocean is given a sharper thermocline
than the model resolves. That is what makes the collocation view show a real,
explainable divergence instead of two curves lying on top of each other.

> Every field is a plausible caricature, not a forecast. The datasets carry
> `synthetic: "true"` and an explicit disclaimer attribute.

---

## Layout

```
backend/
├── app/
│   ├── main.py              app factory, middleware ordering, lifespan
│   ├── config.py            settings; all limits in one auditable block
│   ├── api/v1/              9 route modules
│   ├── core/                logging, error envelope, TTL+LRU cache
│   ├── data/
│   │   ├── adapters/        plugin contract + 3 shipped adapters
│   │   ├── catalog.py       dataset discovery and validated subsetting
│   │   ├── volume.py        quantisation + OCVOL1 container
│   │   ├── colormap.py      cmocean palettes, LUTs, tiles, legends
│   │   ├── derived.py       MLD, Okubo–Weiss, drift, heatwave
│   │   ├── collocation.py   ★ model ↔ observation matching
│   │   └── conventions.py   CF normalisation, variable canon
│   ├── db/                  models, session, repository
│   └── security/            rate limiter, middleware, validators
├── scripts/                 generate_sample_data · ingest · smoke_test
└── tests/                   175 tests
```

---

## Test status

```
175 passed in 4.8s          pytest tests
 69/69 endpoint checks       scripts/smoke_test.py
```

Covered: quantisation round-trip and NaN sentinel handling, colormap
resolution and log scaling, MLD against a synthetic mixed layer, Okubo–Weiss
against solid-body rotation, drift displacement against an analytic uniform
flow, collocation statistics against known offsets, path-traversal rejection,
cell-budget enforcement, rate-limiter behaviour including cool-down, WMS 1.3.0
axis-order handling for `EPSG:4326` vs `CRS:84`, and header-injection defence
on `X-Request-ID`.

---

## Performance

Measured on the demo grid, single worker:

| Operation | Time |
|---|---|
| Volume, 3 steps × 13 levels × 69 × 101 | 62 ms (0.26 MiB, vs 1.0 MiB float32) |
| Depth slice → PNG | 51 ms |
| Transect, 60 points | 18 ms |
| Collocation, one profile | 16 ms |
| Bias map, 40 platforms | 61 ms |
| Eddy census, full domain | 51 ms |
| Drift, 200 particles × 24 h | 88 ms |
| WMS GetMap 700×500 | 24 ms |

The transect and bias-map paths are vectorised — sampling point-by-point made
them 17× and 5× slower respectively, which is the difference between an
interactive drag and a visible stall.

---

## Deployment notes

- Default SQLite needs no external service. Set `OCEANVIEW_DATABASE_URL` to a
  PostgreSQL/PostGIS DSN for deployment; nothing else changes.
- The in-process rate limiter and cache are per-worker. Behind multiple workers
  or a load balancer, back them with Redis — the interfaces are designed for
  that swap.
- Set `OCEANVIEW_ENVIRONMENT=production` to enable HSTS, JSON logs and
  proxy-header trust.
- **Pre-bake the Zarr store and ship it with the demo machine.** Do not depend
  on a live external API at a venue.
