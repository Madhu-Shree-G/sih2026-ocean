"""Exercise every endpoint against the loaded dataset.

Complements the pytest suite: this is a fast, human-readable sweep that
prints one line per endpoint, so a broken route is obvious at a glance.

    python scripts/smoke_test.py
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app.main import app  # noqa: E402

PASS = "PASS"
FAIL = "FAIL"

results: list[tuple[str, str, str, float, str]] = []


def check(
    client: TestClient,
    method: str,
    url: str,
    *,
    expect: int = 200,
    json_body: dict[str, Any] | None = None,
    note: str = "",
    headers: dict[str, str] | None = None,
) -> Any:
    started = time.perf_counter()
    try:
        response = client.request(method, url, json=json_body, headers=headers)
        elapsed = (time.perf_counter() - started) * 1000
        ok = response.status_code == expect
        detail = note
        if not ok:
            detail = f"expected {expect}, got {response.status_code}: {response.text[:180]}"
        results.append((PASS if ok else FAIL, f"{method} {url}", str(response.status_code), elapsed, detail))
        if ok and response.headers.get("content-type", "").startswith("application/json"):
            return response.json()
        return response
    except Exception as exc:  # noqa: BLE001
        elapsed = (time.perf_counter() - started) * 1000
        results.append((FAIL, f"{method} {url}", "EXC", elapsed, f"{type(exc).__name__}: {exc}"))
        return None


def main() -> int:
    with TestClient(app) as client:
        # -- service ---------------------------------------------------------
        check(client, "GET", "/")
        check(client, "GET", "/api/v1/health")
        ready = check(client, "GET", "/api/v1/health/ready")
        check(client, "GET", "/api/v1/health/info")
        check(client, "GET", "/openapi.json")

        if not isinstance(ready, dict) or ready.get("status") != "ready":
            print("Service is not ready; run scripts/generate_sample_data.py first.")
            print(ready)
            return 1

        dataset_id = ready["datasets"][0]

        # -- catalog ---------------------------------------------------------
        check(client, "GET", "/api/v1/datasets")
        check(client, "GET", "/api/v1/datasets/plugins")
        check(client, "GET", f"/api/v1/datasets/{dataset_id}")
        axes = check(client, "GET", f"/api/v1/datasets/{dataset_id}/axes")
        check(client, "GET", f"/api/v1/datasets/{dataset_id}/variables")
        check(client, "GET", "/api/v1/datasets/does_not_exist", expect=404)
        check(client, "GET", "/api/v1/datasets/..%2F..%2Fetc", expect=404, note="path traversal blocked")

        first_time = axes["times"][0] if axes and axes.get("times") else None

        # -- fields ----------------------------------------------------------
        volume = check(
            client, "GET",
            "/api/v1/fields/volume?variable=temperature&bbox=65,5,90,22&depth_max=500&n_times=3",
        )
        if volume is not None and hasattr(volume, "content"):
            results.append((PASS, "  volume payload", "-", 0.0, f"{len(volume.content)} bytes"))

        check(client, "GET", "/api/v1/fields/volume?variable=salinity&n_times=2")
        check(client, "GET", "/api/v1/fields/volume?variable=nonexistent", expect=404)
        check(client, "GET", "/api/v1/fields/slice?variable=temperature&depth=0&format=json")
        check(client, "GET", "/api/v1/fields/slice?variable=temperature&depth=100&format=png")
        check(client, "GET", "/api/v1/fields/slice?variable=u&depth=0&format=binary")
        check(
            client, "GET",
            "/api/v1/fields/transect?start_lat=8&start_lon=72&end_lat=20&end_lon=88&n_points=60",
        )
        check(client, "GET", "/api/v1/fields/profile?lat=12.5&lon=72.3")
        check(client, "GET", "/api/v1/fields/timeseries?lat=12.5&lon=72.3&depth=0")
        check(client, "GET", "/api/v1/fields/hovmoller?lat=12.5&lon=72.3&depth_max=500")
        check(client, "GET", "/api/v1/fields/volume?bbox=200,5,300,22", expect=422, note="bad bbox rejected")
        check(client, "GET", "/api/v1/fields/transect?start_lat=8&start_lon=72&end_lat=8&end_lon=72", expect=422)

        # -- observations ----------------------------------------------------
        platforms = check(client, "GET", "/api/v1/observations/platforms?limit=10")
        check(client, "GET", "/api/v1/observations/platforms?include_trajectory=true&limit=3")
        check(client, "GET", "/api/v1/observations/platforms?bbox=65,5,90,22&limit=5")
        check(client, "GET", "/api/v1/observations/statistics")
        profiles = check(client, "GET", "/api/v1/observations/profiles?limit=5")

        if platforms and platforms.get("platforms"):
            pid = platforms["platforms"][0]["platform_id"]
            check(client, "GET", f"/api/v1/observations/platforms/{pid}")
            check(client, "GET", f"/api/v1/observations/platforms/{pid}/profiles")
        check(client, "GET", "/api/v1/observations/platforms/NO_SUCH_FLOAT", expect=404)

        profile_id = None
        if profiles and profiles.get("profiles"):
            profile_id = profiles["profiles"][0]["profile_id"]
            check(client, "GET", f"/api/v1/observations/profiles/{profile_id}")
        check(client, "GET", "/api/v1/observations/profiles/99999999", expect=404)

        # -- collocation (the core feature) ----------------------------------
        check(client, "GET", "/api/v1/collocation/variables")
        if profile_id is not None:
            collocated = check(
                client, "GET", f"/api/v1/collocation/profile/{profile_id}?variable=temperature"
            )
            if isinstance(collocated, dict) and collocated.get("statistics"):
                stats = collocated["statistics"]
                results.append(
                    (
                        PASS, "  collocation stats", "-", 0.0,
                        "n={0} bias={1} rmsd={2} r={3}".format(
                            stats["n_levels"], stats["bias"], stats["rmsd"], stats["correlation"]
                        ),
                    )
                )
            check(client, "GET", f"/api/v1/collocation/profile/{profile_id}?variable=salinity")
            check(
                client, "GET", f"/api/v1/collocation/profile/{profile_id}?variable=bogus",
                expect=422,
            )

        bias = check(client, "GET", "/api/v1/collocation/bias-map?variable=temperature&limit=40")
        if isinstance(bias, dict):
            results.append(
                (PASS, "  bias-map summary", "-", 0.0,
                 f"{bias['count']} markers, summary={bias['summary'].get('mean_bias')}")
            )

        # -- derived ---------------------------------------------------------
        check(client, "GET", "/api/v1/derived/mixed-layer-depth?bbox=65,5,90,22&stride=2")
        check(client, "GET", "/api/v1/derived/thermocline?bbox=65,5,90,22&stride=2")
        anomaly = check(client, "GET", "/api/v1/derived/anomaly?variable=temperature&bbox=65,5,90,22&stride=2")
        if isinstance(anomaly, dict):
            results.append(
                (PASS, "  anomaly reference", "-", 0.0,
                 f"{anomaly['reference']}, heatwave cells={anomaly['heatwave']['cells_flagged']}")
            )
        eddies = check(client, "GET", "/api/v1/derived/eddies?bbox=60,0,95,25")
        if isinstance(eddies, dict):
            results.append(
                (PASS, "  eddy census", "-", 0.0,
                 f"{eddies['count']} eddies ({eddies['cyclonic']} cyc / {eddies['anticyclonic']} anti)")
            )

        drift = check(
            client, "POST", "/api/v1/derived/drift",
            json_body={"lat": 12.0, "lon": 72.0, "duration_hours": 24, "n_particles": 200},
        )
        if isinstance(drift, dict):
            results.append(
                (PASS, "  drift result", "-", 0.0,
                 f"radius={drift['final_search_radius_km']} km, stranded={drift['particles_stranded']}")
            )
        check(
            client, "POST", "/api/v1/derived/drift",
            json_body={"lat": 88.0, "lon": 72.0}, expect=422, note="origin outside domain",
        )
        check(
            client, "POST", "/api/v1/derived/drift",
            json_body={"lat": 12.0, "lon": 72.0, "n_particles": 99999}, expect=422,
        )

        # -- colormaps -------------------------------------------------------
        check(client, "GET", "/api/v1/colormaps")
        check(client, "GET", "/api/v1/colormaps/thermal/lut")
        check(client, "GET", "/api/v1/colormaps/balance/lut?format=json&reverse=true")
        check(client, "GET", "/api/v1/colormaps/haline/legend?vmin=32&vmax=37&label=Salinity")
        check(client, "GET", "/api/v1/colormaps/not_a_palette/lut", expect=422)

        # -- OGC WMS ---------------------------------------------------------
        check(client, "GET", "/api/v1/wms?SERVICE=WMS&REQUEST=GetCapabilities")
        check(
            client, "GET",
            f"/api/v1/wms?SERVICE=WMS&VERSION=1.3.0&REQUEST=GetMap&LAYERS={dataset_id}/temperature"
            "&CRS=CRS:84&BBOX=65,5,90,22&WIDTH=400&HEIGHT=300&FORMAT=image/png",
        )
        check(
            client, "GET",
            f"/api/v1/wms?SERVICE=WMS&REQUEST=GetLegendGraphic&LAYER={dataset_id}/temperature",
        )
        check(
            client, "GET",
            f"/api/v1/wms?SERVICE=WMS&REQUEST=GetFeatureInfo&QUERY_LAYERS={dataset_id}/temperature"
            "&LAYERS=" + dataset_id + "/temperature&CRS=CRS:84&BBOX=65,5,90,22"
            "&WIDTH=400&HEIGHT=300&I=200&J=150&INFO_FORMAT=application/json",
        )
        check(client, "GET", "/api/v1/wms?SERVICE=WMS&REQUEST=BadOperation", expect=422)
        check(client, "GET", "/api/v1/wms?SERVICE=WFS&REQUEST=GetCapabilities", expect=422)

        # -- security --------------------------------------------------------
        check(client, "POST", "/api/v1/admin/cache/clear", expect=401, note="admin gated")
        check(
            client, "POST", "/api/v1/admin/cache/clear", expect=401,
            headers={"X-Admin-Key": "wrong"}, note="bad admin key rejected",
        )
        headers_probe = client.get("/api/v1/health/info")
        for header in ("X-Content-Type-Options", "X-Frame-Options", "Content-Security-Policy"):
            present = header in headers_probe.headers
            results.append(
                (PASS if present else FAIL, f"  header {header}", "-", 0.0,
                 headers_probe.headers.get(header, "MISSING")[:60])
            )
        rid = headers_probe.headers.get("X-Request-ID", "")
        results.append((PASS if rid else FAIL, "  header X-Request-ID", "-", 0.0, rid[:16]))

    # -- report --------------------------------------------------------------
    failures = [r for r in results if r[0] == FAIL]
    print("\n" + "=" * 108)
    print(f"  {'':4}  {'ENDPOINT':<70} {'CODE':<6} {'ms':>7}  NOTE")
    print("=" * 108)
    for status, endpoint, code, elapsed, note in results:
        marker = "  ok" if status == PASS else "FAIL"
        timing = f"{elapsed:7.1f}" if elapsed else "      -"
        print(f"  {marker:4}  {endpoint:<70} {code:<6} {timing}  {note[:90]}")
    print("=" * 108)
    print(f"  {len(results) - len(failures)}/{len(results)} passed, {len(failures)} failed")
    print("=" * 108 + "\n")

    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
