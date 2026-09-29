/**
 * Data & Services.
 *
 * What is loaded, what it contains, and how another system can pull it. A
 * government data product is judged partly on whether a second department can
 * consume it without emailing anyone, so the OGC WMS endpoint and the REST
 * surface are documented here with copyable URLs rather than left to a
 * developer to discover.
 */

import { Check, Copy, Database, ExternalLink, Server } from "lucide-react";
import { useAppStore } from "@/state/store";
import { useAxes, useColormaps, useDataset, useDatasets, usePlugins, useServiceInfo } from "@/lib/queries";
import { formatDate, formatDepth, titleCase, variableLabel } from "@/lib/format";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHead,
  Disclosure,
  Loading,
  SectionTitle,
  Stat,
  StatGrid,
  TableWrap,
  useToast,
} from "@/ui";
import "./views.css";

const ENDPOINTS: { method: string; path: string; note: string }[] = [
  { method: "GET", path: "/api/v1/datasets", note: "Catalogue of loaded datasets" },
  { method: "GET", path: "/api/v1/datasets/{id}/axes", note: "Time, depth and grid extents" },
  { method: "GET", path: "/api/v1/fields/volume", note: "Quantised 4-D block (OCVOL1)" },
  { method: "GET", path: "/api/v1/fields/slice", note: "One depth level as PNG or binary" },
  { method: "GET", path: "/api/v1/fields/transect", note: "Vertical section along a track" },
  { method: "GET", path: "/api/v1/fields/timeseries", note: "One point through time" },
  { method: "GET", path: "/api/v1/observations/platforms", note: "Floats, gliders, moorings" },
  { method: "GET", path: "/api/v1/observations/profiles/{id}", note: "One cast with all levels" },
  { method: "GET", path: "/api/v1/collocation/profile/{id}", note: "Model against one instrument" },
  { method: "GET", path: "/api/v1/collocation/bias-map", note: "Basin-wide verification" },
  { method: "GET", path: "/api/v1/derived/anomaly", note: "Departure from climatology" },
  { method: "GET", path: "/api/v1/derived/eddies", note: "Okubo–Weiss eddy census" },
  { method: "GET", path: "/api/v1/derived/mixed-layer-depth", note: "Mixed layer depth grid" },
  { method: "GET", path: "/api/v1/derived/thermocline", note: "Thermocline depth grid" },
  { method: "POST", path: "/api/v1/derived/drift", note: "Lagrangian drift simulation" },
  { method: "GET", path: "/api/v1/colormaps", note: "Palette catalogue and swatches" },
];

const WMS_EXAMPLES: { label: string; query: string }[] = [
  { label: "Capabilities", query: "SERVICE=WMS&REQUEST=GetCapabilities" },
  {
    label: "Map tile",
    query:
      "SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS=indofos_demo/temperature&CRS=CRS:84&BBOX=65,5,90,22&WIDTH=800&HEIGHT=600&FORMAT=image/png",
  },
  {
    label: "Legend",
    query: "SERVICE=WMS&REQUEST=GetLegendGraphic&LAYER=indofos_demo/temperature",
  },
];

export function DataServicesView() {
  const datasetId = useAppStore((state) => state.datasetId);
  const info = useServiceInfo(true);
  const datasets = useDatasets(true);
  const dataset = useDataset();
  const axes = useAxes();
  const colormaps = useColormaps();
  const plugins = usePlugins(true);

  if (info.isLoading) return <Loading label="Reading service metadata…" />;

  const origin = window.location.origin;

  return (
    <div className="view">
      <div className="view__inner">
        <header className="view__header">
          <div className="view__lede">
            <h1>Data &amp; services</h1>
            <p>
              What this deployment has loaded, and how another system can consume it. All paths
              below are live on this host.
            </p>
          </div>
          <Button
            variant="secondary"
            onClick={() => window.open(`${origin}/docs`, "_blank", "noopener")}
          >
            <ExternalLink size={16} aria-hidden />
            OpenAPI docs
          </Button>
        </header>

        {/* ---- Service --------------------------------------------------------- */}
        <section aria-label="Service">
          <StatGrid>
            <Stat label="Service" value={info.data?.service ?? "—"} small />
            <Stat label="Version" value={info.data?.version ?? "—"} small />
            <Stat label="Environment" value={titleCase(info.data?.environment ?? "—")} small />
            <Stat label="Datasets loaded" value={datasets.data?.count ?? "—"} small />
          </StatGrid>
        </section>

        {/* ---- Capabilities ----------------------------------------------------- */}
        {info.data && (
          <section>
            <SectionTitle title="Capabilities" subtitle="Reported by the backend, not hard-coded here." />
            <div className="row wrap gap2">
              {Object.entries(info.data.capabilities).map(([name, enabled]) => (
                <Badge key={name} tone={enabled ? "ok" : "neutral"} icon={enabled ? <Check size={12} /> : undefined}>
                  {name.replace(/_/g, " ")}
                </Badge>
              ))}
            </div>
          </section>
        )}

        {/* ---- Dataset ---------------------------------------------------------- */}
        <section aria-labelledby="dataset-heading">
          <SectionTitle title={<span id="dataset-heading">Active dataset</span>} />
          {dataset.data ? (
            <Card>
              <CardHead
                title={dataset.data.title}
                subtitle={dataset.data.summary}
                actions={<Badge tone="info">{dataset.data.id}</Badge>}
              />
              <CardBody>
                <div className="grid3">
                  <Stat label="Institution" value={dataset.data.institution || "—"} small />
                  <Stat label="Source" value={dataset.data.source || "—"} small />
                  <Stat label="Adapter" value={dataset.data.adapter} small />
                  <Stat label="Conventions" value={dataset.data.conventions || "—"} small />
                  <Stat
                    label="Extent"
                    value={`${dataset.data.bbox.min_lon}–${dataset.data.bbox.max_lon}°E`}
                    note={`${dataset.data.bbox.min_lat}–${dataset.data.bbox.max_lat}°N`}
                    small
                  />
                  <Stat
                    label="Time steps"
                    value={axes.data?.times.length ?? "—"}
                    note={
                      axes.data?.times.length
                        ? `${formatDate(axes.data.times[0])} – ${formatDate(
                            axes.data.times[axes.data.times.length - 1],
                          )}`
                        : undefined
                    }
                    small
                  />
                </div>

                <div style={{ marginTop: "var(--s5)" }}>
                  <p className="label" style={{ marginBottom: "var(--s2)" }}>Variables</p>
                  <TableWrap maxHeight={320}>
                    <table className="table">
                      <thead>
                        <tr>
                          <th scope="col">Name</th>
                          <th scope="col">Standard name</th>
                          <th scope="col">Units</th>
                          <th scope="col">Palette</th>
                          <th className="num" scope="col">Default range</th>
                        </tr>
                      </thead>
                      <tbody>
                        {dataset.data.variables.map((spec) => (
                          <tr key={spec.name}>
                            <td className="strong">{variableLabel(spec.name, spec.units, spec.long_name)}</td>
                            <td className="mono muted">{spec.standard_name || "—"}</td>
                            <td className="mono">{spec.units || "—"}</td>
                            <td className="mono muted">{spec.default_colormap}</td>
                            <td className="num">
                              {spec.default_range ? `${spec.default_range[0]} – ${spec.default_range[1]}` : "—"}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableWrap>
                </div>

                {axes.data && axes.data.depths.length > 1 && (
                  <Disclosure summary={`Depth levels (${axes.data.depths.length})`}>
                    <p className="mono">
                      {axes.data.depths.map((depth) => formatDepth(depth)).join(" · ")}
                    </p>
                  </Disclosure>
                )}
              </CardBody>
            </Card>
          ) : (
            <Card><Loading label="Loading dataset metadata…" /></Card>
          )}
        </section>

        {/* ---- REST -------------------------------------------------------------- */}
        <section aria-labelledby="rest-heading">
          <SectionTitle
            title={<span id="rest-heading">REST endpoints</span>}
            subtitle="Every response carries an X-Request-ID header for tracing."
          />
          <div className="stack gap2">
            {ENDPOINTS.map((endpoint) => (
              <EndpointRow key={endpoint.path} {...endpoint} origin={origin} />
            ))}
          </div>
        </section>

        {/* ---- WMS ---------------------------------------------------------------- */}
        <section aria-labelledby="wms-heading">
          <SectionTitle
            title={<span id="wms-heading">OGC WMS</span>}
            subtitle="Point QGIS, ArcGIS or any OGC client at this URL to pull the fields directly."
          />
          <Card>
            <CardBody>
              <div className="stack gap2">
                {WMS_EXAMPLES.map((example) => (
                  <EndpointRow
                    key={example.label}
                    method="GET"
                    path={`/api/v1/wms?${example.query}`}
                    note={example.label}
                    origin={origin}
                  />
                ))}
              </div>
              <p className="muted" style={{ fontSize: "var(--fs-sm)", marginTop: "var(--s4)" }}>
                Layer names take the form <code>{datasetId ?? "dataset"}/variable</code>.
                GetFeatureInfo returns JSON, so a client can query a pixel for its value.
              </p>
            </CardBody>
          </Card>
        </section>

        {/* ---- Palettes ----------------------------------------------------------- */}
        {colormaps.data && (
          <section aria-labelledby="palette-heading">
            <SectionTitle
              title={<span id="palette-heading">Colour palettes</span>}
              subtitle={`${colormaps.data.count} available, served as 256-entry lookup tables.`}
            />
            <Card>
              <CardBody>
                {Object.entries(colormaps.data.groups).map(([group, names]) => (
                  <Disclosure key={group} summary={`${titleCase(group)} (${names.length})`}>
                    {names.map((name) => {
                      const entry = colormaps.data!.colormaps.find((item) => item.name === name);
                      return (
                        <div className="swatchrow" key={name}>
                          <span className="swatchrow__name mono">{name}</span>
                          <span
                            className="swatchrow__bar"
                            style={{
                              background: entry?.swatch?.length
                                ? `linear-gradient(90deg, ${entry.swatch.join(", ")})`
                                : "var(--bg-sunken)",
                            }}
                          />
                        </div>
                      );
                    })}
                  </Disclosure>
                ))}
              </CardBody>
            </Card>
          </section>
        )}

        {/* ---- Plugins & limits ---------------------------------------------------- */}
        <section className="grid2">
          <Card>
            <CardHead
              title={<span className="row gap2"><Database size={18} aria-hidden /> Format plugins</span>}
              subtitle="What this deployment can ingest"
            />
            <CardBody>
              {plugins.data?.plugins.map((plugin) => (
                <div key={plugin.name} style={{ marginBottom: "var(--s4)" }}>
                  <div className="row gap2">
                    <span className="strong mono">{plugin.name}</span>
                    <Badge tone="neutral">{plugin.kind}</Badge>
                  </div>
                  <p className="muted" style={{ fontSize: "var(--fs-sm)" }}>{plugin.description}</p>
                  <p className="faint mono" style={{ fontSize: "var(--fs-xs)" }}>
                    {plugin.suffixes.join("  ")}
                  </p>
                </div>
              )) ?? <Loading label="Loading plugins…" />}
            </CardBody>
          </Card>

          <Card>
            <CardHead
              title={<span className="row gap2"><Server size={18} aria-hidden /> Service limits</span>}
              subtitle="Enforced by the backend"
            />
            <CardBody>
              <TableWrap>
                <table className="table">
                  <tbody>
                    {Object.entries(info.data?.limits ?? {}).map(([name, value]) => (
                      <tr key={name}>
                        <td>{name.replace(/_/g, " ")}</td>
                        <td className="num">{value.toLocaleString("en-IN")}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </TableWrap>
            </CardBody>
          </Card>
        </section>
      </div>
    </div>
  );
}

function EndpointRow({
  method,
  path,
  note,
  origin,
}: {
  method: string;
  path: string;
  note: string;
  origin: string;
}) {
  const toast = useToast();
  const url = `${origin}${path}`;

  return (
    <div className="endpoint">
      <span className="endpoint__method">{method}</span>
      <span className="endpoint__path">{path}</span>
      <span className="muted" style={{ fontFamily: "var(--font-sans)", flex: "none" }}>{note}</span>
      <Button
        variant="ghost"
        size="sm"
        onClick={() =>
          navigator.clipboard
            ?.writeText(url)
            .then(() => toast("URL copied"))
            .catch(() => toast("Could not copy"))
        }
        aria-label={`Copy the URL for ${path}`}
      >
        <Copy size={14} aria-hidden />
      </Button>
    </div>
  );
}
