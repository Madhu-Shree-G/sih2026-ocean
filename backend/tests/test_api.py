"""Integration tests exercising the HTTP surface end to end."""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.data.volume import unpack
from tests.conftest import requires_data

pytestmark = requires_data


# ---------------------------------------------------------------------------
# Service basics
# ---------------------------------------------------------------------------
class TestService:
    def test_root_advertises_entrypoints(self, client: TestClient) -> None:
        payload = client.get("/").json()
        assert payload["docs"] == "/docs"
        assert "wms_capabilities" in payload

    def test_liveness(self, client: TestClient) -> None:
        payload = client.get("/api/v1/health").json()
        assert payload["status"] == "ok"

    def test_readiness_reports_datasets(self, client: TestClient) -> None:
        payload = client.get("/api/v1/health/ready").json()
        assert payload["status"] == "ready"
        assert payload["checks"]["database"] == "ok"
        assert payload["datasets"]

    def test_info_declares_capabilities_and_limits(self, client: TestClient) -> None:
        payload = client.get("/api/v1/health/info").json()
        assert payload["capabilities"]["collocation"] is True
        assert payload["limits"]["max_volume_cells"] > 0
        assert payload["plugins"]

    def test_openapi_schema_builds(self, client: TestClient) -> None:
        schema = client.get("/openapi.json").json()
        assert "/api/v1/fields/volume" in schema["paths"]
        assert len(schema["paths"]) >= 30

    def test_unknown_route_returns_structured_error(self, client: TestClient) -> None:
        response = client.get("/api/v1/does-not-exist")
        assert response.status_code == 404
        assert response.json()["error"]["code"] == "not_found"


# ---------------------------------------------------------------------------
# Catalog
# ---------------------------------------------------------------------------
class TestCatalog:
    def test_list_datasets(self, client: TestClient) -> None:
        payload = client.get("/api/v1/datasets").json()
        assert payload["count"] >= 1
        assert payload["datasets"][0]["variables"]

    def test_describe_dataset_has_axes_and_bbox(
        self, client: TestClient, dataset_id: str
    ) -> None:
        payload = client.get(f"/api/v1/datasets/{dataset_id}").json()
        assert payload["id"] == dataset_id
        assert {"lat", "lon", "depth", "time"} <= set(payload["axes"])
        assert payload["bbox"]["min_lon"] < payload["bbox"]["max_lon"]
        assert payload["conventions"].startswith("CF-")

    def test_variables_carry_cf_metadata(self, client: TestClient, dataset_id: str) -> None:
        payload = client.get(f"/api/v1/datasets/{dataset_id}/variables").json()
        by_name = {v["name"]: v for v in payload["variables"]}
        assert "temperature" in by_name
        assert by_name["temperature"]["standard_name"] == "sea_water_potential_temperature"
        assert by_name["temperature"]["units"] == "degree_Celsius"

    def test_velocity_components_share_a_vector_group(
        self, client: TestClient, dataset_id: str
    ) -> None:
        payload = client.get(f"/api/v1/datasets/{dataset_id}/variables").json()
        by_name = {v["name"]: v for v in payload["variables"]}
        assert by_name["u"]["vector_group"] == "current"
        assert by_name["v"]["vector_group"] == "current"

    def test_plugin_registry_lists_adapters(self, client: TestClient) -> None:
        payload = client.get("/api/v1/datasets/plugins").json()
        names = {p["name"] for p in payload["plugins"]}
        assert {"netcdf_model", "argo_netcdf", "csv_profile"} <= names
        assert payload["entry_point_group"] == "oceanview.adapters"

    def test_unknown_dataset_is_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/datasets/nope").status_code == 404

    @pytest.mark.parametrize("attack", ["..%2F..%2Fetc", "a%00b", "with%20space"])
    def test_dataset_id_rejects_traversal(self, client: TestClient, attack: str) -> None:
        assert client.get(f"/api/v1/datasets/{attack}").status_code in (404, 422)


# ---------------------------------------------------------------------------
# Fields
# ---------------------------------------------------------------------------
class TestFields:
    def test_volume_returns_decodable_container(
        self, client: TestClient, dataset_id: str
    ) -> None:
        response = client.get(
            "/api/v1/fields/volume",
            params={"variable": "temperature", "bbox": "65,5,90,22",
                    "depth_max": 500, "n_times": 2},
        )
        assert response.status_code == 200
        assert response.headers["X-Ocean-Format"] == "OCVOL1"

        header, data = unpack(response.content)
        n_time, n_depth, n_lat, n_lon = header["shape"]
        assert n_time == 2
        assert data.size == n_time * n_depth * n_lat * n_lon
        assert data.dtype == np.uint8
        assert header["axis_order"] == ["time", "depth", "lat", "lon"]

    def test_volume_values_dequantise_into_physical_range(
        self, client: TestClient
    ) -> None:
        response = client.get(
            "/api/v1/fields/volume",
            params={"variable": "temperature", "bbox": "70,8,80,18", "depth_max": 200},
        )
        header, data = unpack(response.content)

        valid = data[data >= header["min_valid_raw"]].astype("float64")
        values = header["offset"] + (valid - header["min_valid_raw"]) * header["scale"]
        assert values.min() > -5.0
        assert values.max() < 40.0

    def test_land_cells_are_marked_no_data(self, client: TestClient) -> None:
        # A box centred on peninsular India must contain masked cells.
        response = client.get(
            "/api/v1/fields/volume", params={"variable": "temperature", "bbox": "74,14,82,22"}
        )
        header, data = unpack(response.content)
        assert header["nodata_count"] > 0
        assert (data == header["nodata_raw"]).any()

    def test_time_animation_returns_requested_steps(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/fields/volume", params={"variable": "temperature", "n_times": 5, "stride": 4}
        )
        header, _ = unpack(response.content)
        assert header["shape"][0] == 5
        assert len(header["times"]) == 5

    def test_auto_stride_keeps_whole_domain_requests_servable(
        self, client: TestClient
    ) -> None:
        response = client.get("/api/v1/fields/volume", params={"variable": "temperature"})
        assert response.status_code == 200
        header, _ = unpack(response.content)
        assert header["stride"] >= 1

    def test_slice_json_shape_matches_axes(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/fields/slice",
            params={"variable": "temperature", "depth": 0, "format": "json",
                    "bbox": "70,8,80,18", "stride": 2},
        ).json()
        rows, cols = payload["shape"]
        assert len(payload["values"]) == rows
        assert len(payload["values"][0]) == cols
        assert len(payload["lats"]) == rows
        assert len(payload["lons"]) == cols

    def test_slice_png_is_an_image(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/fields/slice",
            params={"variable": "temperature", "depth": 50, "format": "png"},
        )
        assert response.headers["content-type"] == "image/png"
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_slice_selects_the_nearest_available_depth(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/fields/slice",
            params={"variable": "temperature", "depth": 137, "format": "json", "stride": 8},
        ).json()
        assert payload["depth_m"] >= 0

    def test_transect_returns_a_depth_section(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/fields/transect",
            params={"start_lat": 8, "start_lon": 72, "end_lat": 20, "end_lon": 88,
                    "n_points": 50, "depth_max": 500},
        ).json()

        assert payload["n_points"] == 50
        assert len(payload["distance_km"]) == 50
        assert len(payload["track"]) == 50
        assert len(payload["values"]) == len(payload["depth_m"])
        assert len(payload["values"][0]) == 50
        assert payload["total_distance_km"] > 0
        # Distance must increase monotonically along the track.
        assert all(
            b >= a for a, b in zip(payload["distance_km"], payload["distance_km"][1:])
        )

    def test_transect_respects_the_point_cap(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/fields/transect",
            params={"start_lat": 8, "start_lon": 72, "end_lat": 20, "end_lon": 88,
                    "n_points": 100000},
        )
        assert response.status_code == 422

    def test_point_profile_is_ordered_by_depth(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/fields/profile", params={"lat": 12.5, "lon": 72.3}
        ).json()
        depths = payload["depth_m"]
        assert depths == sorted(depths)
        assert len(payload["values"]) == len(depths)

    def test_profile_temperature_decreases_with_depth(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/fields/profile",
            params={"lat": 12.5, "lon": 68.0, "variable": "temperature"},
        ).json()
        values = [v for v in payload["values"] if v is not None]
        assert len(values) > 5
        # Surface must be warmer than the deepest sampled level.
        assert values[0] > values[-1]

    def test_timeseries_length_matches_time_axis(
        self, client: TestClient, dataset_id: str
    ) -> None:
        axes = client.get(f"/api/v1/datasets/{dataset_id}/axes").json()
        payload = client.get(
            "/api/v1/fields/timeseries", params={"lat": 12.5, "lon": 72.3, "depth": 0}
        ).json()
        assert len(payload["times"]) == len(axes["times"])

    def test_hovmoller_is_depth_by_time(self, client: TestClient, dataset_id: str) -> None:
        axes = client.get(f"/api/v1/datasets/{dataset_id}/axes").json()
        payload = client.get(
            "/api/v1/fields/hovmoller",
            params={"lat": 12.5, "lon": 72.3, "depth_max": 500},
        ).json()
        assert len(payload["values"]) == len(payload["depth_m"])
        assert len(payload["values"][0]) == len(axes["times"])

    def test_unknown_variable_is_404(self, client: TestClient) -> None:
        assert client.get(
            "/api/v1/fields/volume", params={"variable": "unobtainium"}
        ).status_code == 404

    @pytest.mark.parametrize(
        "bbox", ["200,5,300,22", "90,5,60,20", "not,a,bbox,here", "1,2,3"]
    )
    def test_malformed_bbox_is_422(self, client: TestClient, bbox: str) -> None:
        assert client.get(
            "/api/v1/fields/volume", params={"bbox": bbox}
        ).status_code == 422


# ---------------------------------------------------------------------------
# Observations
# ---------------------------------------------------------------------------
class TestObservations:
    def test_platforms_listing(self, client: TestClient) -> None:
        payload = client.get("/api/v1/observations/platforms", params={"limit": 20}).json()
        assert payload["count"] > 0
        platform = payload["platforms"][0]
        assert platform["platform_id"]
        assert platform["last_position"]["lat"] is not None

    def test_platform_types_are_represented(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/observations/platforms", params={"limit": 500}
        ).json()
        kinds = {p["platform_type"] for p in payload["platforms"]}
        assert "argo_float" in kinds
        assert {"glider", "ctd"} & kinds

    def test_trajectory_is_time_ordered(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/observations/platforms",
            params={"include_trajectory": "true", "limit": 3},
        ).json()
        track = next(
            (p["trajectory"] for p in payload["platforms"] if len(p["trajectory"]) > 1),
            None,
        )
        if track is None:
            pytest.skip("No multi-cycle platform available.")
        times = [point["time"] for point in track]
        assert times == sorted(times)

    def test_bbox_filter_constrains_results(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/observations/platforms", params={"bbox": "70,8,80,18", "limit": 200}
        ).json()
        for platform in payload["platforms"]:
            position = platform["last_position"]
            assert 70 <= position["lon"] <= 80
            assert 8 <= position["lat"] <= 18

    def test_profile_measurements_are_aligned(
        self, client: TestClient, profile_id: int
    ) -> None:
        payload = client.get(f"/api/v1/observations/profiles/{profile_id}").json()
        measurements = payload["measurements"]
        n = len(measurements["depth_m"])
        assert n > 0
        for key in ("temperature", "salinity", "chlorophyll", "oxygen"):
            assert len(measurements[key]) == n

    def test_statistics_are_consistent(self, client: TestClient) -> None:
        payload = client.get("/api/v1/observations/statistics").json()
        assert payload["platforms"] > 0
        assert payload["profiles"] >= payload["platforms"]
        assert payload["measurement_levels"] > payload["profiles"]
        assert payload["time_coverage"]["start"] < payload["time_coverage"]["end"]

    def test_unknown_platform_is_404(self, client: TestClient) -> None:
        assert client.get(
            "/api/v1/observations/platforms/NOT_A_FLOAT"
        ).status_code == 404

    def test_unknown_profile_is_404(self, client: TestClient) -> None:
        assert client.get("/api/v1/observations/profiles/99999999").status_code == 404


# ---------------------------------------------------------------------------
# Collocation - the core capability
# ---------------------------------------------------------------------------
class TestCollocation:
    def test_profile_collocation_pairs_both_series(
        self, client: TestClient, profile_id: int
    ) -> None:
        payload = client.get(
            f"/api/v1/collocation/profile/{profile_id}", params={"variable": "temperature"}
        ).json()

        profile = payload["profile"]
        n = len(profile["depth_m"])
        assert n > 0
        assert len(profile["observed"]) == n
        assert len(profile["modelled"]) == n
        assert len(profile["difference"]) == n

    def test_collocation_reports_verification_metrics(
        self, client: TestClient, profile_id: int
    ) -> None:
        payload = client.get(
            f"/api/v1/collocation/profile/{profile_id}", params={"variable": "temperature"}
        ).json()
        stats = payload["statistics"]

        assert stats is not None
        assert stats["n_levels"] > 2
        for key in ("bias", "rmsd", "mae", "correlation"):
            assert key in stats
        # RMSD can never be smaller than |bias|.
        assert stats["rmsd"] >= abs(stats["bias"]) - 1e-9

    def test_difference_equals_model_minus_observation(
        self, client: TestClient, profile_id: int
    ) -> None:
        payload = client.get(
            f"/api/v1/collocation/profile/{profile_id}", params={"variable": "temperature"}
        ).json()
        profile = payload["profile"]

        checked = 0
        for observed, modelled, difference in zip(
            profile["observed"], profile["modelled"], profile["difference"]
        ):
            if observed is None or modelled is None:
                continue
            assert difference == pytest.approx(modelled - observed, abs=1e-3)
            checked += 1
        assert checked > 0

    def test_collocation_records_spacetime_offsets(
        self, client: TestClient, profile_id: int
    ) -> None:
        payload = client.get(
            f"/api/v1/collocation/profile/{profile_id}", params={"variable": "temperature"}
        ).json()
        assert payload["grid_distance_km"] >= 0
        assert payload["model_time"]
        assert payload["observation_time"]

    def test_salinity_collocation_also_works(
        self, client: TestClient, profile_id: int
    ) -> None:
        payload = client.get(
            f"/api/v1/collocation/profile/{profile_id}", params={"variable": "salinity"}
        ).json()
        assert payload["units"] == "psu"

    def test_non_comparable_variable_is_rejected(
        self, client: TestClient, profile_id: int
    ) -> None:
        assert client.get(
            f"/api/v1/collocation/profile/{profile_id}", params={"variable": "u"}
        ).status_code == 422

    def test_bias_map_returns_markers_and_summary(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/collocation/bias-map",
            params={"variable": "temperature", "limit": 60},
        ).json()

        assert payload["count"] > 0
        assert payload["summary"]["profiles_matched"] == payload["count"]
        assert payload["suggested_scale"]["colormap"] == "balance"

        marker = payload["markers"][0]
        for key in ("platform_id", "lat", "lon", "bias", "rmsd", "n_levels"):
            assert key in marker

    def test_bias_map_scale_is_symmetric(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/collocation/bias-map", params={"variable": "temperature", "limit": 30}
        ).json()
        scale = payload["suggested_scale"]
        assert scale["vmin"] == pytest.approx(-scale["vmax"])

    def test_comparable_variables_endpoint(self, client: TestClient) -> None:
        payload = client.get("/api/v1/collocation/variables").json()
        assert "temperature" in payload["comparable"]


# ---------------------------------------------------------------------------
# Derived products
# ---------------------------------------------------------------------------
class TestDerived:
    def test_mixed_layer_depth_is_physical(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/derived/mixed-layer-depth",
            params={"bbox": "65,5,90,22", "stride": 3},
        ).json()

        assert payload["units"] == "m"
        values = [
            v for row in payload["grid"]["values"] for v in row if v is not None
        ]
        assert values
        assert min(values) >= 0
        assert max(values) <= 2000

    def test_thermocline_endpoint(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/derived/thermocline", params={"bbox": "65,5,90,22", "stride": 4}
        ).json()
        assert payload["product"] == "thermocline_depth"
        assert payload["grid"]["shape"][0] > 0

    def test_anomaly_uses_the_climatology_store(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/derived/anomaly",
            params={"variable": "temperature", "bbox": "60,0,95,25", "stride": 3},
        ).json()
        assert payload["reference"].endswith("_climatology")
        assert payload["reference_note"] is None
        assert payload["colormap"] == "balance"

    def test_heatwave_emerges_over_the_run(self, client: TestClient, dataset_id: str) -> None:
        """The generator embeds an intensifying Arabian Sea heatwave."""
        axes = client.get(f"/api/v1/datasets/{dataset_id}/axes").json()
        last = len(axes["times"]) - 1

        first_payload = client.get(
            "/api/v1/derived/anomaly",
            params={"bbox": "60,0,95,25", "stride": 3, "time_index": 0},
        ).json()
        last_payload = client.get(
            "/api/v1/derived/anomaly",
            params={"bbox": "60,0,95,25", "stride": 3, "time_index": last},
        ).json()

        assert (
            last_payload["heatwave"]["cells_flagged"]
            > first_payload["heatwave"]["cells_flagged"]
        )

    def test_eddy_census_returns_classified_eddies(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/derived/eddies", params={"bbox": "60,0,95,25"}
        ).json()

        assert payload["count"] > 0
        assert payload["cyclonic"] + payload["anticyclonic"] == payload["count"]

        eddy = payload["eddies"][0]
        assert eddy["polarity"] in {"cyclonic", "anticyclonic"}
        assert eddy["radius_km"] > 0
        assert eddy["area_km2"] > 0
        assert -90 <= eddy["centre"]["lat"] <= 90

    def test_eddies_are_sorted_by_area(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/derived/eddies", params={"bbox": "60,0,95,25"}
        ).json()
        areas = [e["area_km2"] for e in payload["eddies"]]
        assert areas == sorted(areas, reverse=True)

    def test_drift_produces_a_growing_search_area(self, client: TestClient) -> None:
        payload = client.post(
            "/api/v1/derived/drift",
            json={"lat": 12.0, "lon": 68.0, "duration_hours": 36,
                  "n_particles": 250, "diffusion_m2_s": 20.0},
        ).json()

        assert payload["product"] == "lagrangian_drift"
        assert len(payload["positions"]) == len(payload["times_hours"])
        assert len(payload["positions"][0]) == 250
        assert payload["search_radius_km"][-1] > payload["search_radius_km"][0]
        assert payload["disclaimer"]

    def test_drift_is_reproducible_for_a_fixed_seed(self, client: TestClient) -> None:
        body = {"lat": 12.0, "lon": 68.0, "duration_hours": 12,
                "n_particles": 50, "seed": 4242}
        first = client.post("/api/v1/derived/drift", json=body).json()
        second = client.post("/api/v1/derived/drift", json=body).json()
        assert first["final_centroid"] == second["final_centroid"]

    def test_drift_rejects_an_origin_outside_the_domain(self, client: TestClient) -> None:
        assert client.post(
            "/api/v1/derived/drift", json={"lat": 80.0, "lon": 70.0}
        ).status_code == 422

    def test_drift_enforces_the_particle_cap(self, client: TestClient) -> None:
        assert client.post(
            "/api/v1/derived/drift", json={"lat": 12.0, "lon": 68.0, "n_particles": 999999}
        ).status_code == 422

    def test_drift_rejects_unknown_fields(self, client: TestClient) -> None:
        assert client.post(
            "/api/v1/derived/drift",
            json={"lat": 12.0, "lon": 68.0, "sneaky_field": True},
        ).status_code == 422


# ---------------------------------------------------------------------------
# Colormaps
# ---------------------------------------------------------------------------
class TestColormapEndpoints:
    def test_catalog_is_grouped(self, client: TestClient) -> None:
        payload = client.get("/api/v1/colormaps").json()
        assert "oceanographic" in payload["groups"]
        assert payload["count"] > 10

    def test_lut_is_exactly_1024_bytes(self, client: TestClient) -> None:
        response = client.get("/api/v1/colormaps/thermal/lut")
        assert len(response.content) == 256 * 4
        assert response.headers["X-Ocean-LUT-Size"] == "256"

    def test_lut_json_form(self, client: TestClient) -> None:
        payload = client.get(
            "/api/v1/colormaps/balance/lut", params={"format": "json"}
        ).json()
        assert len(payload["rgba"]) == 256
        assert len(payload["rgba"][0]) == 4

    def test_legend_renders(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/colormaps/haline/legend",
            params={"vmin": 32, "vmax": 37, "label": "Salinity"},
        )
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_unknown_palette_is_422(self, client: TestClient) -> None:
        assert client.get("/api/v1/colormaps/no_such_map/lut").status_code == 422


# ---------------------------------------------------------------------------
# OGC WMS
# ---------------------------------------------------------------------------
class TestWMS:
    def test_capabilities_is_wms_130(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/wms", params={"SERVICE": "WMS", "REQUEST": "GetCapabilities"}
        )
        assert response.status_code == 200
        body = response.text
        assert 'version="1.3.0"' in body
        assert "<Name>WMS</Name>" in body
        assert "CRS:84" in body

    def test_capabilities_advertises_every_variable(
        self, client: TestClient, dataset_id: str
    ) -> None:
        body = client.get(
            "/api/v1/wms", params={"SERVICE": "WMS", "REQUEST": "GetCapabilities"}
        ).text
        for variable in ("temperature", "salinity", "u", "v"):
            assert f"<Name>{dataset_id}/{variable}</Name>" in body

    def test_getmap_returns_the_requested_size(
        self, client: TestClient, dataset_id: str
    ) -> None:
        from io import BytesIO

        from PIL import Image

        response = client.get(
            "/api/v1/wms",
            params={"SERVICE": "WMS", "VERSION": "1.3.0", "REQUEST": "GetMap",
                    "LAYERS": f"{dataset_id}/temperature", "CRS": "CRS:84",
                    "BBOX": "65,5,90,22", "WIDTH": 320, "HEIGHT": 240,
                    "FORMAT": "image/png"},
        )
        assert response.status_code == 200
        assert Image.open(BytesIO(response.content)).size == (320, 240)

    def test_getmap_parameters_are_case_insensitive(
        self, client: TestClient, dataset_id: str
    ) -> None:
        response = client.get(
            "/api/v1/wms",
            params={"service": "wms", "request": "GetMap",
                    "layers": f"{dataset_id}/temperature", "crs": "CRS:84",
                    "bbox": "65,5,90,22", "width": 64, "height": 64,
                    "format": "image/png"},
        )
        assert response.status_code == 200

    def test_epsg4326_uses_lat_lon_axis_order(
        self, client: TestClient, dataset_id: str
    ) -> None:
        """WMS 1.3.0 flips axis order for EPSG:4326 relative to CRS:84."""
        crs84 = client.get(
            "/api/v1/wms",
            params={"SERVICE": "WMS", "REQUEST": "GetMap",
                    "LAYERS": f"{dataset_id}/temperature", "CRS": "CRS:84",
                    "BBOX": "65,5,90,22", "WIDTH": 64, "HEIGHT": 64,
                    "FORMAT": "image/png"},
        )
        epsg = client.get(
            "/api/v1/wms",
            params={"SERVICE": "WMS", "REQUEST": "GetMap",
                    "LAYERS": f"{dataset_id}/temperature", "CRS": "EPSG:4326",
                    "BBOX": "5,65,22,90", "WIDTH": 64, "HEIGHT": 64,
                    "FORMAT": "image/png"},
        )
        assert crs84.status_code == epsg.status_code == 200
        assert crs84.content == epsg.content

    def test_out_of_footprint_request_returns_transparent_tile(
        self, client: TestClient, dataset_id: str
    ) -> None:
        response = client.get(
            "/api/v1/wms",
            params={"SERVICE": "WMS", "REQUEST": "GetMap",
                    "LAYERS": f"{dataset_id}/temperature", "CRS": "CRS:84",
                    "BBOX": "-170,-80,-160,-70", "WIDTH": 32, "HEIGHT": 32,
                    "FORMAT": "image/png"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "image/png"

    def test_getfeatureinfo_returns_geojson(
        self, client: TestClient, dataset_id: str
    ) -> None:
        payload = client.get(
            "/api/v1/wms",
            params={"SERVICE": "WMS", "REQUEST": "GetFeatureInfo",
                    "LAYERS": f"{dataset_id}/temperature",
                    "QUERY_LAYERS": f"{dataset_id}/temperature", "CRS": "CRS:84",
                    "BBOX": "65,5,90,22", "WIDTH": 400, "HEIGHT": 300,
                    "I": 200, "J": 150},
        ).json()

        feature = payload["features"][0]
        assert feature["geometry"]["type"] == "Point"
        assert feature["properties"]["units"] == "degree_Celsius"

    def test_legend_graphic(self, client: TestClient, dataset_id: str) -> None:
        response = client.get(
            "/api/v1/wms",
            params={"SERVICE": "WMS", "REQUEST": "GetLegendGraphic",
                    "LAYER": f"{dataset_id}/temperature"},
        )
        assert response.content[:8] == b"\x89PNG\r\n\x1a\n"

    def test_oversized_image_is_rejected(self, client: TestClient, dataset_id: str) -> None:
        assert client.get(
            "/api/v1/wms",
            params={"SERVICE": "WMS", "REQUEST": "GetMap",
                    "LAYERS": f"{dataset_id}/temperature", "CRS": "CRS:84",
                    "BBOX": "65,5,90,22", "WIDTH": 99999, "HEIGHT": 99999,
                    "FORMAT": "image/png"},
        ).status_code == 422

    @pytest.mark.parametrize(
        "params",
        [
            {"SERVICE": "WFS", "REQUEST": "GetCapabilities"},
            {"SERVICE": "WMS", "REQUEST": "Nonsense"},
            {"SERVICE": "WMS", "REQUEST": "GetMap"},
        ],
    )
    def test_invalid_wms_requests_are_422(
        self, client: TestClient, params: dict
    ) -> None:
        assert client.get("/api/v1/wms", params=params).status_code == 422


# ---------------------------------------------------------------------------
# Security
# ---------------------------------------------------------------------------
class TestSecurity:
    def test_security_headers_are_present(self, client: TestClient) -> None:
        headers = client.get("/api/v1/health/info").headers
        assert headers["X-Content-Type-Options"] == "nosniff"
        assert headers["X-Frame-Options"] == "DENY"
        assert "Content-Security-Policy" in headers
        assert "Permissions-Policy" in headers

    def test_request_id_is_returned(self, client: TestClient) -> None:
        assert client.get("/api/v1/health").headers.get("X-Request-ID")

    def test_supplied_request_id_is_echoed(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/health", headers={"X-Request-ID": "trace-abc-123"}
        )
        assert response.headers["X-Request-ID"] == "trace-abc-123"

    def test_malicious_request_id_is_replaced(self, client: TestClient) -> None:
        response = client.get(
            "/api/v1/health", headers={"X-Request-ID": "bad id\r\nInjected: yes"}
        )
        assert response.headers["X-Request-ID"] != "bad id\r\nInjected: yes"
        assert "Injected" not in response.headers

    def test_admin_routes_require_a_key(self, client: TestClient) -> None:
        assert client.post("/api/v1/admin/cache/clear").status_code == 401
        assert client.get("/api/v1/admin/stats").status_code == 401

    def test_admin_rejects_a_wrong_key(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/admin/catalog/reload", headers={"X-Admin-Key": "guess"}
        )
        assert response.status_code == 401

    def test_overlong_query_string_is_rejected(self, client: TestClient) -> None:
        response = client.get("/api/v1/datasets", params={"junk": "x" * 6000})
        assert response.status_code == 414

    def test_oversized_request_body_is_rejected(self, client: TestClient) -> None:
        response = client.post(
            "/api/v1/derived/drift",
            content=b"x" * (2 * 1024 * 1024),
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 413

    def test_error_responses_use_one_envelope(self, client: TestClient) -> None:
        for url in (
            "/api/v1/datasets/missing",
            "/api/v1/observations/profiles/99999999",
            "/api/v1/fields/volume?bbox=bad",
        ):
            body = client.get(url).json()
            assert "error" in body
            assert {"code", "message", "request_id"} <= set(body["error"])

    def test_internal_paths_are_not_leaked(self, client: TestClient) -> None:
        body = client.get("/api/v1/datasets/missing").text
        assert "Traceback" not in body
        assert "site-packages" not in body

    def test_rate_limit_headers_are_published(self, client: TestClient) -> None:
        client.app.state.rate_limiter.enabled = True
        try:
            response = client.get("/api/v1/datasets")
            assert "X-RateLimit-Limit" in response.headers
            assert "X-RateLimit-Remaining" in response.headers
            assert int(response.headers["X-RateLimit-Remaining"]) <= int(
                response.headers["X-RateLimit-Limit"]
            )
        finally:
            client.app.state.rate_limiter.reset()
            client.app.state.rate_limiter.enabled = False

    def test_rate_limiter_eventually_returns_429(self, client: TestClient) -> None:
        limiter = client.app.state.rate_limiter
        limiter.enabled = True
        limiter.reset()
        try:
            statuses = {
                client.get("/api/v1/colormaps").status_code for _ in range(500)
            }
            assert 429 in statuses
        finally:
            limiter.reset()
            limiter.enabled = False

    def test_health_is_exempt_from_rate_limiting(self, client: TestClient) -> None:
        limiter = client.app.state.rate_limiter
        limiter.enabled = True
        limiter.reset()
        try:
            for _ in range(400):
                client.get("/api/v1/colormaps")
            assert client.get("/api/v1/health").status_code == 200
        finally:
            limiter.reset()
            limiter.enabled = False
