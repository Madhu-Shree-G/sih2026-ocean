"""Unit tests for the data, science and security layers."""

from __future__ import annotations

import numpy as np
import pytest

from app.core.cache import TTLCache, cache_key
from app.core.errors import PayloadTooLargeError, ValidationError
from app.data.collocation import (
    compute_statistics,
    haversine_km,
    interpolate_to_depths,
)
from app.data.colormap import ColorScale, lut, render_png, resolve_colormap
from app.data.derived import (
    VelocityField,
    detect_eddies,
    heatwave_mask,
    mixed_layer_depth,
    okubo_weiss,
    simulate_drift,
    thermocline_depth,
)
from app.data.volume import (
    MIN_VALID_RAW,
    NODATA_RAW,
    build_volume_payload,
    pack,
    quantise,
    subsample_to_budget,
    unpack,
)
from app.security.ratelimit import RateLimiter
from app.security.validation import (
    clamp_int,
    guard_cell_budget,
    parse_bbox,
    parse_depth_range,
    parse_iso_time,
    safe_identifier,
)


# ---------------------------------------------------------------------------
# Volume quantisation
# ---------------------------------------------------------------------------
class TestQuantisation:
    def test_roundtrip_preserves_values_within_one_quantum(self) -> None:
        values = np.linspace(2.0, 32.0, 500).astype("float32")
        field = quantise(values)
        recovered = field.dequantise()

        quantum = (field.vmax - field.vmin) / 254
        assert np.nanmax(np.abs(recovered - values)) <= quantum

    def test_nan_maps_to_reserved_sentinel(self) -> None:
        values = np.array([1.0, np.nan, 3.0], dtype="float32")
        field = quantise(values)

        assert field.data[1] == NODATA_RAW
        assert field.nodata_count == 1
        assert np.all(field.data[[0, 2]] >= MIN_VALID_RAW)
        assert np.isnan(field.dequantise()[1])

    def test_all_nan_input_does_not_crash(self) -> None:
        field = quantise(np.full((3, 3), np.nan, dtype="float32"))
        assert field.nodata_count == 9
        assert np.all(field.data == NODATA_RAW)

    def test_constant_field_produces_valid_scale(self) -> None:
        field = quantise(np.full(10, 7.5, dtype="float32"))
        assert field.scale > 0
        assert np.all(np.isfinite(field.dequantise()))

    def test_explicit_range_clamps_outliers(self) -> None:
        values = np.array([-100.0, 15.0, 200.0], dtype="float32")
        field = quantise(values, vmin=0.0, vmax=30.0)
        recovered = field.dequantise()

        assert recovered[0] == pytest.approx(0.0, abs=0.2)
        assert recovered[2] == pytest.approx(30.0, abs=0.2)

    def test_pack_unpack_roundtrip(self) -> None:
        payload = np.arange(24, dtype="uint8").reshape(2, 3, 4)
        header = {"shape": [2, 3, 4], "variable": "temperature"}

        decoded_header, decoded = unpack(pack(header, payload))
        assert decoded_header["variable"] == "temperature"
        np.testing.assert_array_equal(decoded, payload)

    def test_unpack_rejects_foreign_buffer(self) -> None:
        with pytest.raises(ValueError, match="magic"):
            unpack(b"NOTOCVOL" + b"\x00" * 32)

    def test_pack_rejects_non_uint8(self) -> None:
        with pytest.raises(TypeError):
            pack({"shape": [2]}, np.array([1.0, 2.0], dtype="float32"))

    def test_volume_payload_header_is_complete(self) -> None:
        values = np.random.default_rng(0).normal(20, 3, (2, 4, 5, 6)).astype("float32")
        blob = build_volume_payload(
            values=values, variable="temperature", units="degree_Celsius",
            dataset_id="test", lats=np.linspace(0, 10, 5), lons=np.linspace(60, 70, 6),
            depths=np.linspace(0, 100, 4), times=["2024-03-01T00:00:00Z", "2024-03-02T00:00:00Z"],
            colormap="thermal",
        )
        header, data = unpack(blob)

        assert header["shape"] == [2, 4, 5, 6]
        assert header["axis_order"] == ["time", "depth", "lat", "lon"]
        assert header["nodata_raw"] == 0
        assert data.shape == (2, 4, 5, 6)

    def test_subsample_picks_a_fitting_stride(self) -> None:
        stride = subsample_to_budget(1000, 1000, 50, 10, max_cells=1_000_000)
        cells = (1000 // stride) ** 2 * 50 * 10
        assert cells <= 1_000_000


# ---------------------------------------------------------------------------
# Colour handling
# ---------------------------------------------------------------------------
class TestColormaps:
    def test_lut_shape_and_dtype(self) -> None:
        table = lut("thermal")
        assert table.shape == (256, 4)
        assert table.dtype == np.uint8

    def test_reverse_flips_the_ramp(self) -> None:
        forward = lut("viridis")
        backward = lut("viridis", reverse=True)
        np.testing.assert_array_equal(forward[0], backward[-1])

    def test_unknown_palette_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            resolve_colormap("definitely_not_a_palette")

    def test_log_scale_masks_non_positive_values(self) -> None:
        scale = ColorScale(name="algae", vmin=0.01, vmax=10.0, scale="log")
        normalised = scale.normalise(np.array([-1.0, 0.0, 1.0]))
        assert np.isnan(normalised[0]) and np.isnan(normalised[1])
        assert 0.0 <= normalised[2] <= 1.0

    def test_render_png_emits_a_png(self) -> None:
        field = np.random.default_rng(1).normal(25, 2, (16, 20))
        blob = render_png(field, ColorScale(name="thermal", vmin=20, vmax=30))
        assert blob[:8] == b"\x89PNG\r\n\x1a\n"

    def test_nodata_becomes_transparent(self) -> None:
        from app.data.colormap import render_rgba

        field = np.array([[np.nan, 1.0], [2.0, 3.0]])
        rgba = render_rgba(field, ColorScale(name="thermal", vmin=0, vmax=4))
        assert rgba[0, 0, 3] == 0
        assert rgba[1, 1, 3] == 255

    def test_render_rejects_non_2d(self) -> None:
        with pytest.raises(ValidationError):
            render_png(np.zeros((2, 2, 2)), ColorScale(name="thermal", vmin=0, vmax=1))


# ---------------------------------------------------------------------------
# Derived diagnostics
# ---------------------------------------------------------------------------
class TestDerived:
    @staticmethod
    def _column(mld_target: float = 50.0) -> tuple[np.ndarray, np.ndarray]:
        depths = np.array([0, 10, 20, 30, 40, 50, 60, 80, 100, 150, 200], dtype="float64")
        surface = 28.0
        profile = np.where(depths <= mld_target, surface, surface - (depths - mld_target) * 0.1)
        block = np.repeat(profile[:, None, None], 4, axis=1).repeat(5, axis=2)
        return depths, block

    def test_mld_finds_the_mixed_layer(self) -> None:
        depths, block = self._column(mld_target=50.0)
        mld = mixed_layer_depth(block, depths)
        # The 0.2 degC criterion is met just below the uniform layer.
        assert np.all(np.abs(mld - 52.0) < 12.0)

    def test_mld_returns_nan_over_land(self) -> None:
        depths, block = self._column()
        block[:, 0, 0] = np.nan
        assert np.isnan(mixed_layer_depth(block, depths)[0, 0])

    def test_mld_rejects_mismatched_depth_axis(self) -> None:
        _, block = self._column()
        with pytest.raises(ValidationError):
            mixed_layer_depth(block, np.array([0.0, 10.0]))

    def test_thermocline_sits_below_the_mixed_layer(self) -> None:
        depths, block = self._column(mld_target=50.0)
        result = thermocline_depth(block, depths)
        assert np.all(result[np.isfinite(result)] >= 40.0)

    def test_okubo_weiss_is_negative_inside_solid_rotation(self) -> None:
        lats = np.linspace(-2, 2, 41)
        lons = np.linspace(-2, 2, 41)
        lon_grid, lat_grid = np.meshgrid(lons, lats)
        # Solid-body rotation: pure vorticity, no strain, so W < 0.
        u = -lat_grid * 0.5
        v = lon_grid * 0.5

        fields = okubo_weiss(u, v, lats, lons)
        centre = fields["w"][20, 20]
        assert centre < 0

    def test_detect_eddies_finds_a_planted_vortex(self) -> None:
        lats = np.linspace(5, 15, 60)
        lons = np.linspace(65, 75, 60)
        lon_grid, lat_grid = np.meshgrid(lons, lats)

        radius = 1.2
        dx = lon_grid - 70.0
        dy = lat_grid - 10.0
        envelope = np.exp(-(dx**2 + dy**2) / (2 * radius**2))
        u = -dy * envelope
        v = dx * envelope

        eddies, w = detect_eddies(u, v, lats, lons, min_cells=4)
        assert len(eddies) >= 1
        assert w.shape == (60, 60)

        strongest = eddies[0]
        assert abs(strongest.centre_lat - 10.0) < 2.0
        assert abs(strongest.centre_lon - 70.0) < 2.0
        assert strongest.polarity in {"cyclonic", "anticyclonic"}
        assert strongest.area_km2 > 0

    def test_detect_eddies_on_uniform_flow_finds_nothing(self) -> None:
        lats = np.linspace(0, 10, 30)
        lons = np.linspace(60, 70, 30)
        eddies, _ = detect_eddies(np.ones((30, 30)), np.zeros((30, 30)), lats, lons)
        assert eddies == []

    def test_heatwave_mask_counts_exceedances(self) -> None:
        field = np.array([[0.0, 1.5], [2.5, np.nan]])
        result = heatwave_mask(field, threshold=1.0)
        assert result["cells_flagged"] == 2
        assert result["cells_valid"] == 3
        assert result["max_anomaly"] == pytest.approx(2.5)

    def test_anomaly_rejects_incompatible_shapes(self) -> None:
        from app.data.derived import anomaly

        with pytest.raises(ValidationError):
            anomaly(np.zeros((4, 4)), np.zeros((3, 5)))


# ---------------------------------------------------------------------------
# Drift simulation
# ---------------------------------------------------------------------------
class TestDrift:
    @staticmethod
    def _uniform_eastward(speed: float = 0.5) -> VelocityField:
        lats = np.linspace(5.0, 15.0, 41)
        lons = np.linspace(65.0, 75.0, 41)
        return VelocityField(
            np.full((41, 41), speed), np.zeros((41, 41)), lats, lons
        )

    def test_particles_move_east_in_eastward_flow(self) -> None:
        velocity = self._uniform_eastward(0.5)
        result = simulate_drift(
            velocity, origin_lat=10.0, origin_lon=70.0,
            n_particles=100, duration_hours=24, diffusion_m2_s=0.0,
            initial_spread_km=0.0,
        )
        start_lon = result.centroid[0][0]
        end_lon = result.centroid[-1][0]

        # 0.5 m/s for 24 h is ~43 km, roughly 0.4 deg at this latitude.
        assert end_lon > start_lon
        assert 0.25 < (end_lon - start_lon) < 0.6

    def test_cloud_spreads_under_diffusion(self) -> None:
        velocity = self._uniform_eastward(0.0)
        result = simulate_drift(
            velocity, origin_lat=10.0, origin_lon=70.0,
            n_particles=300, duration_hours=48, diffusion_m2_s=50.0,
            initial_spread_km=1.0,
        )
        assert result.radius_km[-1] > result.radius_km[0]

    def test_simulation_is_reproducible(self) -> None:
        velocity = self._uniform_eastward(0.3)
        kwargs = dict(
            origin_lat=10.0, origin_lon=70.0, n_particles=50,
            duration_hours=12, seed=99,
        )
        first = simulate_drift(velocity, **kwargs)
        second = simulate_drift(velocity, **kwargs)
        assert first.centroid[-1] == second.centroid[-1]

    def test_land_cells_are_treated_as_zero_velocity(self) -> None:
        lats = np.linspace(5.0, 15.0, 21)
        lons = np.linspace(65.0, 75.0, 21)
        u = np.full((21, 21), 0.5)
        u[:, 15:] = np.nan
        velocity = VelocityField(u, np.zeros((21, 21)), lats, lons)

        sampled_u, _, on_water = velocity.sample(
            np.array([10.0]), np.array([74.5])
        )
        assert sampled_u[0] == 0.0
        assert not bool(on_water[0])

    def test_velocity_field_rejects_shape_mismatch(self) -> None:
        with pytest.raises(ValidationError):
            VelocityField(
                np.zeros((4, 4)), np.zeros((4, 4)),
                np.linspace(0, 1, 5), np.linspace(0, 1, 4),
            )


# ---------------------------------------------------------------------------
# Collocation maths
# ---------------------------------------------------------------------------
class TestCollocation:
    def test_interpolation_matches_known_values(self) -> None:
        model_depths = np.array([0.0, 100.0, 200.0])
        model_values = np.array([30.0, 20.0, 10.0])
        result = interpolate_to_depths(model_depths, model_values, np.array([50.0, 150.0]))

        assert result[0] == pytest.approx(25.0)
        assert result[1] == pytest.approx(15.0)

    def test_no_extrapolation_below_deepest_level(self) -> None:
        result = interpolate_to_depths(
            np.array([0.0, 100.0]), np.array([30.0, 20.0]), np.array([500.0])
        )
        assert np.isnan(result[0])

    def test_insufficient_model_data_returns_nan(self) -> None:
        result = interpolate_to_depths(
            np.array([0.0, 100.0]), np.array([np.nan, np.nan]), np.array([50.0])
        )
        assert np.isnan(result[0])

    def test_statistics_on_a_known_offset(self) -> None:
        observed = np.array([20.0, 19.0, 18.0, 17.0])
        modelled = observed + 0.5
        stats = compute_statistics(observed, modelled, np.array([0.0, 10.0, 20.0, 30.0]))

        assert stats is not None
        assert stats.bias == pytest.approx(0.5)
        assert stats.rmsd == pytest.approx(0.5)
        assert stats.mae == pytest.approx(0.5)
        assert stats.correlation == pytest.approx(1.0)
        assert stats.count == 4

    def test_statistics_ignore_unpaired_levels(self) -> None:
        # Levels 1 and 3 pair; levels 2 and 4 each miss one series.
        observed = np.array([20.0, np.nan, 18.0, 17.0])
        modelled = np.array([20.5, 19.5, 18.5, np.nan])
        stats = compute_statistics(observed, modelled, np.array([0.0, 10.0, 20.0, 30.0]))

        assert stats is not None
        assert stats.count == 2
        assert stats.bias == pytest.approx(0.5)

    def test_single_paired_level_is_not_enough_for_statistics(self) -> None:
        # One matched level cannot support a correlation, so the contract is
        # to return None rather than a misleading metric.
        observed = np.array([20.0, np.nan, 18.0])
        modelled = np.array([20.5, 19.5, np.nan])
        assert compute_statistics(
            observed, modelled, np.array([0.0, 10.0, 20.0])
        ) is None

    def test_statistics_return_none_when_nothing_pairs(self) -> None:
        assert compute_statistics(
            np.array([np.nan, np.nan]), np.array([1.0, 2.0]), np.array([0.0, 10.0])
        ) is None

    def test_constant_series_yields_nan_correlation_not_a_crash(self) -> None:
        stats = compute_statistics(
            np.array([20.0, 20.0, 20.0]), np.array([21.0, 21.0, 21.0]),
            np.array([0.0, 10.0, 20.0]),
        )
        assert stats is not None
        assert np.isnan(stats.correlation)
        assert stats.bias == pytest.approx(1.0)

    def test_haversine_against_a_known_distance(self) -> None:
        # One degree of latitude is ~111.2 km.
        assert haversine_km(0.0, 0.0, 1.0, 0.0) == pytest.approx(111.19, abs=0.5)
        assert haversine_km(10.0, 70.0, 10.0, 70.0) == pytest.approx(0.0)


# ---------------------------------------------------------------------------
# Validation / firewall
# ---------------------------------------------------------------------------
class TestValidation:
    @pytest.mark.parametrize(
        "value",
        ["../etc/passwd", "a/b", "a\\b", "with space", "", "x" * 65, "semi:colon", "~home"],
    )
    def test_unsafe_identifiers_are_rejected(self, value: str) -> None:
        with pytest.raises(ValidationError):
            safe_identifier(value)

    @pytest.mark.parametrize("value", ["temperature", "indofos_demo", "a-b_C9", "x"])
    def test_safe_identifiers_pass(self, value: str) -> None:
        assert safe_identifier(value) == value

    def test_bbox_parses_ogc_axis_order(self) -> None:
        assert parse_bbox("60,5,90,20", default=(0, 0, 1, 1)) == (60.0, 5.0, 90.0, 20.0)

    def test_bbox_default_when_absent(self) -> None:
        assert parse_bbox(None, default=(1, 2, 3, 4)) == (1, 2, 3, 4)

    @pytest.mark.parametrize(
        "value",
        ["1,2,3", "a,b,c,d", "90,5,60,20", "60,20,90,5", "60,-95,90,95", "1,2,3,4,5"],
    )
    def test_malformed_bbox_is_rejected(self, value: str) -> None:
        with pytest.raises(ValidationError):
            parse_bbox(value, default=(0, 0, 1, 1))

    def test_depth_range_clamps_to_available(self) -> None:
        assert parse_depth_range(None, None, available_min=0, available_max=2000) == (0, 2000)
        assert parse_depth_range(-10, 5000, available_min=0, available_max=2000) == (0, 2000)

    def test_inverted_depth_range_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parse_depth_range(500, 100, available_min=0, available_max=2000)

    def test_depth_window_outside_dataset_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parse_depth_range(5000, 6000, available_min=0, available_max=2000)

    def test_cell_budget_blocks_oversized_requests(self) -> None:
        with pytest.raises(PayloadTooLargeError):
            guard_cell_budget(
                n_lat=5000, n_lon=5000, n_depth=50, n_time=10,
                max_cells=1_000_000, max_bytes=10_000_000,
            )

    def test_cell_budget_blocks_oversized_bytes(self) -> None:
        with pytest.raises(PayloadTooLargeError):
            guard_cell_budget(
                n_lat=1000, n_lon=1000, bytes_per_cell=8,
                max_cells=10_000_000, max_bytes=1_000_000,
            )

    def test_empty_subset_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            guard_cell_budget(n_lat=0, n_lon=10, max_cells=100, max_bytes=100)

    def test_cell_budget_allows_reasonable_requests(self) -> None:
        assert guard_cell_budget(
            n_lat=100, n_lon=100, n_depth=25, n_time=5,
            max_cells=40_000_000, max_bytes=96 * 1024 * 1024,
        ) == 1_250_000

    def test_iso_time_handles_z_suffix(self) -> None:
        parsed = parse_iso_time("2024-03-01T12:00:00Z")
        assert parsed is not None and parsed.hour == 12

    def test_naive_time_is_assumed_utc(self) -> None:
        parsed = parse_iso_time("2024-03-01T12:00:00")
        assert parsed is not None and parsed.tzinfo is not None

    def test_bad_time_is_rejected(self) -> None:
        with pytest.raises(ValidationError):
            parse_iso_time("not-a-date")

    def test_clamp_int_bounds(self) -> None:
        assert clamp_int(None, default=5, minimum=1, maximum=10, field="n") == 5
        with pytest.raises(ValidationError):
            clamp_int(99, default=5, minimum=1, maximum=10, field="n")


# ---------------------------------------------------------------------------
# Rate limiter
# ---------------------------------------------------------------------------
class TestRateLimiter:
    def test_allows_traffic_within_budget(self) -> None:
        limiter = RateLimiter(default_per_minute=60, heavy_per_minute=10)
        assert all(limiter.check("client-a").allowed for _ in range(30))

    def test_blocks_once_the_bucket_empties(self) -> None:
        limiter = RateLimiter(default_per_minute=10, heavy_per_minute=2, burst_multiplier=1.0)
        decisions = [limiter.check("client-b") for _ in range(20)]
        assert any(not d.allowed for d in decisions)

        rejected = next(d for d in decisions if not d.allowed)
        assert rejected.retry_after > 0
        assert rejected.remaining == 0

    def test_remaining_never_exceeds_the_advertised_limit(self) -> None:
        # The bucket carries a burst allowance above the per-minute limit, but
        # a client reading the headers must never see remaining > limit.
        limiter = RateLimiter(
            default_per_minute=10, heavy_per_minute=5, burst_multiplier=3.0
        )
        decision = limiter.check("client-headers")
        assert decision.allowed
        assert decision.remaining <= decision.limit

    def test_heavy_and_default_buckets_are_independent(self) -> None:
        limiter = RateLimiter(default_per_minute=100, heavy_per_minute=2, burst_multiplier=1.0)
        for _ in range(5):
            limiter.check("client-c", "heavy")
        assert limiter.check("client-c", "default").allowed

    def test_clients_are_isolated(self) -> None:
        limiter = RateLimiter(default_per_minute=5, heavy_per_minute=5, burst_multiplier=1.0)
        for _ in range(20):
            limiter.check("noisy")
        assert limiter.check("quiet").allowed

    def test_sustained_abuse_triggers_cooldown(self) -> None:
        limiter = RateLimiter(
            default_per_minute=2, heavy_per_minute=2,
            burst_multiplier=1.0, max_violations=3, block_seconds=30,
        )
        for _ in range(40):
            limiter.check("abuser")
        decision = limiter.check("abuser")
        assert not decision.allowed
        assert decision.reason in {"cooldown", "rate_limited"}

    def test_disabled_limiter_always_allows(self) -> None:
        limiter = RateLimiter(default_per_minute=1, heavy_per_minute=1, enabled=False)
        assert all(limiter.check("anyone").allowed for _ in range(50))

    def test_reset_clears_state(self) -> None:
        limiter = RateLimiter(default_per_minute=2, heavy_per_minute=2, burst_multiplier=1.0)
        for _ in range(10):
            limiter.check("client-d")
        limiter.reset()
        assert limiter.stats()["tracked_clients"] == 0


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------
class TestCache:
    def test_get_or_set_computes_once(self) -> None:
        cache = TTLCache(max_entries=4, ttl_seconds=60)
        calls = {"n": 0}

        def factory() -> str:
            calls["n"] += 1
            return "value"

        assert cache.get_or_set("k", factory) == "value"
        assert cache.get_or_set("k", factory) == "value"
        assert calls["n"] == 1

    def test_lru_eviction_respects_capacity(self) -> None:
        cache = TTLCache(max_entries=2, ttl_seconds=60)
        cache.set("a", 1)
        cache.set("b", 2)
        cache.set("c", 3)
        assert cache.stats()["entries"] == 2
        assert cache.get("a") is None

    def test_disabled_cache_never_stores(self) -> None:
        cache = TTLCache(max_entries=4, ttl_seconds=60, enabled=False)
        cache.set("a", 1)
        assert cache.get("a") is None

    def test_cache_key_is_stable_and_order_independent(self) -> None:
        assert cache_key("p", a=1, b=2) == cache_key("p", b=2, a=1)
        assert cache_key("p", a=1) != cache_key("p", a=2)
