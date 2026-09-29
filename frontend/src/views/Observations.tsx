/**
 * Observations — what is actually measuring the ocean, and what it measured.
 *
 * The platform network was previously reachable only by clicking a dot on a
 * dark globe and hoping you hit it. Everything is here as a table you can
 * sort, search and reach with a keyboard, and the endpoints that describe the
 * network (`/observations/statistics`, `/observations/profiles/{id}`) are on
 * screen instead of unused.
 */

import { useMemo, useState } from "react";
import { MapPin, Radio, Search, Waves } from "lucide-react";
import { useAppStore } from "@/state/store";
import { useObservationStatistics, usePlatforms, useProfile } from "@/lib/queries";
import { formatDate, formatLatLon, formatUtc, platformLabel, titleCase } from "@/lib/format";
import { PLATFORM_COLORS } from "@/lib/cesium-setup";
import {
  Badge,
  Button,
  Card,
  CardBody,
  CardHead,
  Dot,
  EmptyState,
  Loading,
  SectionTitle,
  SortHeader,
  Stat,
  StatGrid,
  TableWrap,
  useSort,
} from "@/ui";
import type { Platform } from "@/types/api";
import "./views.css";

type Column = "platform_id" | "platform_type" | "profile_count" | "last_observation" | "project";

export function ObservationsView() {
  const { selectedProfileId, selectProfile, focusOnMap } = useAppStore();
  const [query, setQuery] = useState("");
  const [typeFilter, setTypeFilter] = useState<string>("all");

  const platforms = usePlatforms(true);
  const statistics = useObservationStatistics(true);
  const profile = useProfile(selectedProfileId);

  const sort = useSort<Column>("profile_count", "desc");

  const rows = useMemo(() => {
    const list = platforms.data?.platforms ?? [];
    const needle = query.trim().toLowerCase();

    const filtered = list.filter((platform) => {
      if (typeFilter !== "all" && platform.platform_type !== typeFilter) return false;
      if (!needle) return true;
      return (
        platform.platform_id.toLowerCase().includes(needle) ||
        (platform.wmo_id ?? "").toLowerCase().includes(needle) ||
        (platform.project ?? "").toLowerCase().includes(needle) ||
        (platform.institution ?? "").toLowerCase().includes(needle)
      );
    });

    return [...filtered].sort((a, b) => sort.compare(a[sort.key], b[sort.key]));
  }, [platforms.data, query, typeFilter, sort]);

  const openPlatform = (platform: Platform) => {
    const track = platform.trajectory ?? [];
    const latest = track.length > 0 ? track[track.length - 1] : null;
    if (latest) selectProfile(latest.profile_id, platform.platform_id);
  };

  if (platforms.isLoading) return <Loading label="Loading the observing network…" />;

  const types = platforms.data?.platform_types ?? [];

  return (
    <div className="view">
      <div className="view__inner">
        <header className="view__header">
          <div className="view__lede">
            <h1>Observations</h1>
            <p>
              Every float, glider and CTD cast in the archive, with the profiles each one has
              returned. Selecting a platform loads its most recent profile below and marks it on
              the map.
            </p>
          </div>
        </header>

        {/* ---- Network summary ---------------------------------------------- */}
        <section aria-label="Network summary">
          <StatGrid>
            <Stat label="Platforms" value={statistics.data?.platforms ?? "—"} />
            <Stat
              label="Profiles"
              value={statistics.data?.profiles?.toLocaleString("en-IN") ?? "—"}
            />
            <Stat
              label="Measurement levels"
              value={statistics.data?.measurement_levels?.toLocaleString("en-IN") ?? "—"}
            />
            <Stat
              label="Coverage"
              value={
                statistics.data?.time_coverage.start
                  ? formatDate(statistics.data.time_coverage.start)
                  : "—"
              }
              note={
                statistics.data?.time_coverage.end
                  ? `to ${formatDate(statistics.data.time_coverage.end)}`
                  : undefined
              }
              small
            />
          </StatGrid>
        </section>

        {/* ---- By type -------------------------------------------------------- */}
        {statistics.data && (
          <section>
            <SectionTitle title="Platform types" />
            <div className="grid3">
              {Object.entries(statistics.data.platforms_by_type).map(([type, count]) => (
                <Card key={type} variant="flat">
                  <CardBody tight>
                    <div className="row gap3">
                      <Dot color={PLATFORM_COLORS[type] ?? "#94a3b8"} />
                      <span className="grow strong">{platformLabel(type)}</span>
                      <span className="mono">{count}</span>
                    </div>
                  </CardBody>
                </Card>
              ))}
            </div>
          </section>
        )}

        {/* ---- Table ---------------------------------------------------------- */}
        <section aria-labelledby="platforms-heading">
          <SectionTitle
            title={<span id="platforms-heading">Platforms</span>}
            subtitle={`${rows.length} shown`}
            actions={
              <div className="row gap3 wrap">
                <div className="row gap2">
                  <Search size={16} aria-hidden className="muted" />
                  <input
                    className="control"
                    style={{ minWidth: 200 }}
                    placeholder="Search id, WMO, project…"
                    value={query}
                    onChange={(event) => setQuery(event.target.value)}
                    aria-label="Search platforms"
                  />
                </div>
                <select
                  className="control"
                  style={{ width: "auto" }}
                  value={typeFilter}
                  onChange={(event) => setTypeFilter(event.target.value)}
                  aria-label="Filter by platform type"
                >
                  <option value="all">All types</option>
                  {types.map((type) => (
                    <option key={type} value={type}>
                      {platformLabel(type)}
                    </option>
                  ))}
                </select>
              </div>
            }
          />

          {rows.length === 0 ? (
            <Card>
              <EmptyState
                icon={<Radio size={24} />}
                title="No platforms match"
                body="Clear the search box or choose a different platform type."
              />
            </Card>
          ) : (
            <TableWrap maxHeight={460}>
              <table className="table table--clickable">
                <thead>
                  <tr>
                    <SortHeader columnKey="platform_id" active={sort.key === "platform_id"} direction={sort.direction} onSort={sort.onSort}>
                      Platform
                    </SortHeader>
                    <SortHeader columnKey="platform_type" active={sort.key === "platform_type"} direction={sort.direction} onSort={sort.onSort}>
                      Type
                    </SortHeader>
                    <SortHeader columnKey="project" active={sort.key === "project"} direction={sort.direction} onSort={sort.onSort}>
                      Project
                    </SortHeader>
                    <SortHeader columnKey="profile_count" active={sort.key === "profile_count"} direction={sort.direction} onSort={sort.onSort} numeric>
                      Profiles
                    </SortHeader>
                    <SortHeader columnKey="last_observation" active={sort.key === "last_observation"} direction={sort.direction} onSort={sort.onSort}>
                      Last seen
                    </SortHeader>
                    <th scope="col">Last position</th>
                    <th scope="col"><span className="sr-only">Actions</span></th>
                  </tr>
                </thead>
                <tbody>
                  {rows.map((platform) => {
                    const track = platform.trajectory ?? [];
                    const latest = track.length > 0 ? track[track.length - 1] : null;
                    const selected = latest?.profile_id === selectedProfileId;
                    return (
                      <tr
                        key={platform.platform_id}
                        aria-selected={selected}
                        onClick={() => openPlatform(platform)}
                        tabIndex={0}
                        onKeyDown={(event) => {
                          if (event.key === "Enter" || event.key === " ") {
                            event.preventDefault();
                            openPlatform(platform);
                          }
                        }}
                      >
                        <td>
                          <span className="row gap2">
                            <Dot color={PLATFORM_COLORS[platform.platform_type] ?? "#94a3b8"} />
                            <span className="mono strong">{platform.platform_id}</span>
                          </span>
                        </td>
                        <td>{platformLabel(platform.platform_type)}</td>
                        <td className="muted">{platform.project ?? "—"}</td>
                        <td className="num">{platform.profile_count}</td>
                        <td className="mono">{formatDate(platform.last_observation)}</td>
                        <td className="mono muted">
                          {platform.last_position
                            ? formatLatLon(platform.last_position.lat, platform.last_position.lon, 1)
                            : "—"}
                        </td>
                        <td>
                          {platform.last_position && (
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={(event) => {
                                event.stopPropagation();
                                focusOnMap(platform.last_position!.lat, platform.last_position!.lon);
                              }}
                            >
                              <MapPin size={14} aria-hidden />
                              Map
                            </Button>
                          )}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            </TableWrap>
          )}
        </section>

        {/* ---- Selected profile ------------------------------------------------ */}
        <section aria-labelledby="profile-heading">
          <SectionTitle title={<span id="profile-heading">Selected profile</span>} />
          {selectedProfileId === null ? (
            <Card>
              <EmptyState
                icon={<Waves size={24} />}
                title="No profile selected"
                body="Choose a platform in the table above, or click one of its markers on the map."
              />
            </Card>
          ) : profile.isLoading ? (
            <Card>
              <Loading label="Loading the profile…" />
            </Card>
          ) : profile.data ? (
            <Card>
              <CardHead
                title={
                  <span className="row gap3">
                    <span className="mono">{profile.data.platform_id ?? "—"}</span>
                    <Badge tone="info">Cycle {profile.data.cycle}</Badge>
                    <Badge tone="neutral">{titleCase(profile.data.data_mode)}</Badge>
                  </span>
                }
                subtitle={`${formatUtc(profile.data.time)} · ${formatLatLon(
                  profile.data.location.lat,
                  profile.data.location.lon,
                )}`}
                actions={
                  <Button
                    variant="secondary"
                    size="sm"
                    onClick={() =>
                      focusOnMap(profile.data!.location.lat, profile.data!.location.lon)
                    }
                  >
                    <MapPin size={14} aria-hidden />
                    Show on map
                  </Button>
                }
              />
              <CardBody>
                <StatGrid>
                  <Stat label="Levels" value={profile.data.n_levels} small />
                  <Stat label="Max depth" value={`${Math.round(profile.data.max_depth_m)} m`} small />
                  <Stat
                    label="Surface temp."
                    value={
                      profile.data.surface_temperature !== null
                        ? `${profile.data.surface_temperature.toFixed(2)} °C`
                        : "—"
                    }
                    small
                  />
                  <Stat
                    label="Surface salinity"
                    value={
                      profile.data.surface_salinity !== null
                        ? `${profile.data.surface_salinity.toFixed(2)} psu`
                        : "—"
                    }
                    small
                  />
                </StatGrid>

                <div style={{ marginTop: "var(--s5)" }}>
                  <TableWrap maxHeight={320}>
                    <table className="table">
                      <thead>
                        <tr>
                          <th className="num" scope="col">Depth (m)</th>
                          <th className="num" scope="col">Temp (°C)</th>
                          <th className="num" scope="col">Salinity (psu)</th>
                          <th className="num" scope="col">Chlorophyll</th>
                          <th className="num" scope="col">Oxygen</th>
                        </tr>
                      </thead>
                      <tbody>
                        {profile.data.measurements.depth_m.map((depth, index) => (
                          <tr key={index}>
                            <td className="num">{depth.toFixed(1)}</td>
                            <td className="num">{fmt(profile.data!.measurements.temperature[index])}</td>
                            <td className="num">{fmt(profile.data!.measurements.salinity[index])}</td>
                            <td className="num">{fmt(profile.data!.measurements.chlorophyll[index])}</td>
                            <td className="num">{fmt(profile.data!.measurements.oxygen[index])}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </TableWrap>
                </div>
              </CardBody>
            </Card>
          ) : (
            <Card>
              <EmptyState
                icon={<Waves size={24} />}
                title="Could not load that profile"
                body="The backend did not return measurements for this profile id."
                tone="warn"
              />
            </Card>
          )}
        </section>
      </div>
    </div>
  );
}

function fmt(value: number | null): string {
  return value === null || !Number.isFinite(value) ? "—" : value.toFixed(2);
}
