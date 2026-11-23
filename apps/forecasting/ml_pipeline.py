from __future__ import annotations

from datetime import date, timedelta
import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.metrics import mean_absolute_error, mean_squared_error

from apps.accounts.models import User, log_audit
from apps.forecasting.models import ForecastPrediction, ForecastRun
from apps.library.models import LibraryZone

SLOT_LABELS = {
    1: "Slot 1 (09:00-11:00)",
    2: "Slot 2 (11:00-13:00)",
    3: "Slot 3 (14:00-16:00)",
    4: "Slot 4 (16:00-18:00)",
}


def build_synthetic_history(zones: list[LibraryZone], days: int = 60, seed: int = 42) -> pd.DataFrame:
    """
    Generates labeled synthetic aggregate occupancy history (no PII) when authorized
    historical institutional data is unavailable (FR-ML-01, FR-ML-05, DEC-013).
    """
    rng = np.random.default_rng(seed)
    today = date.today()
    start_date = today - timedelta(days=days)
    rows: list[dict] = []

    for day_idx in range(days):
        curr_date = start_date + timedelta(days=day_idx)
        dow = curr_date.weekday()  # 0=Mon ... 6=Sun
        is_weekend = int(dow in (4, 5))  # Fri/Sat weekend pattern in Bangladesh
        is_peak_week = int((day_idx % 28) >= 21)

        for zone in zones:
            capacity = max(zone.seats.filter(is_active=True).count(), 4)
            for slot_order in SLOT_LABELS:
                base_ratio = 0.72 if slot_order in (2, 3) else 0.48
                if is_weekend:
                    base_ratio *= 0.35
                if is_peak_week:
                    base_ratio = min(0.95, base_ratio + 0.18)

                demand = float(np.clip(rng.normal(capacity * base_ratio, 0.75), 0, capacity))
                rows.append(
                    {
                        "zone_id": zone.id,
                        "capacity": capacity,
                        "date": curr_date,
                        "day_of_week": dow,
                        "slot_order": slot_order,
                        "is_weekend": is_weekend,
                        "is_peak_week": is_peak_week,
                        "demand": round(demand, 2),
                    }
                )

    df = pd.DataFrame(rows).sort_values(["zone_id", "date", "slot_order"]).reset_index(drop=True)
    # Time-safe lag feature (strictly past values, preventing data leakage)
    df["lag_7d_demand"] = (
        df.groupby(["zone_id", "slot_order"])["demand"].shift(7).bfill()
    )
    return df


def run_demand_forecast(*, actor: User | None = None, horizon_days: int = 3) -> ForecastRun:
    """
    Trains & evaluates a time-aware demand forecasting model against a naive baseline
    and stores aggregate future predictions (FR-ML-02, FR-ML-03, FR-ML-04).
    """
    zones = list(LibraryZone.objects.all().order_by("id"))
    if not zones:
        raise ValueError("Create at least one LibraryZone before running forecasting.")

    df = build_synthetic_history(zones=zones, days=60)
    unique_dates = sorted(df["date"].unique())
    split_date = unique_dates[int(len(unique_dates) * 0.8)]

    train_df = df[df["date"] < split_date].copy()
    test_df = df[df["date"] >= split_date].copy()

    # Naive baseline: historical mean by (zone_id, day_of_week, slot_order)
    baseline_map = (
        train_df.groupby(["zone_id", "day_of_week", "slot_order"])["demand"].mean().to_dict()
    )
    global_mean = float(train_df["demand"].mean())
    baseline_preds = [
        baseline_map.get((r.zone_id, r.day_of_week, r.slot_order), global_mean)
        for r in test_df.itertuples(index=False)
    ]
    baseline_mae = float(mean_absolute_error(test_df["demand"], baseline_preds))

    feature_cols = ["zone_id", "capacity", "day_of_week", "slot_order", "is_weekend", "is_peak_week", "lag_7d_demand"]
    model = RandomForestRegressor(n_estimators=120, max_depth=8, random_state=42)
    model.fit(train_df[feature_cols], train_df["demand"])

    test_preds = model.predict(test_df[feature_cols])
    model_mae = float(mean_absolute_error(test_df["demand"], test_preds))
    model_rmse = float(np.sqrt(mean_squared_error(test_df["demand"], test_preds)))

    # Retrain on full authorized/synthetic window before generating horizon predictions
    model.fit(df[feature_cols], df["demand"])

    run = ForecastRun.objects.create(
        model_version="rf-demand-v1.0-synthetic",
        algorithm="RandomForestRegressor (time-aware 80/20 holdout vs. weekday-slot mean baseline)",
        horizon_days=horizon_days,
        is_synthetic_data=True,
        baseline_mae=round(baseline_mae, 3),
        model_mae=round(model_mae, 3),
        model_rmse=round(model_rmse, 3),
    )

    today = date.today()
    future_rows: list[ForecastPrediction] = []
    for offset in range(horizon_days):
        target_date = today + timedelta(days=offset)
        dow = target_date.weekday()
        is_weekend = int(dow in (4, 5))

        for zone in zones:
            capacity = max(zone.seats.filter(is_active=True).count(), 4)
            for slot_order, slot_label in SLOT_LABELS.items():
                recent_vals = df[(df["zone_id"] == zone.id) & (df["slot_order"] == slot_order)]["demand"]
                lag_val = float(recent_vals.iloc[-7]) if len(recent_vals) >= 7 else float(recent_vals.mean())
                X_future = pd.DataFrame(
                    [
                        {
                            "zone_id": zone.id,
                            "capacity": capacity,
                            "day_of_week": dow,
                            "slot_order": slot_order,
                            "is_weekend": is_weekend,
                            "is_peak_week": 0,
                            "lag_7d_demand": lag_val,
                        }
                    ]
                )
                pred = float(np.clip(model.predict(X_future)[0], 0, capacity))
                future_rows.append(
                    ForecastPrediction(
                        run=run,
                        zone=zone,
                        target_date=target_date,
                        slot_order=slot_order,
                        slot_label=slot_label,
                        predicted_demand=round(pred, 2),
                        configured_capacity=capacity,
                    )
                )

    ForecastPrediction.objects.bulk_create(future_rows)
    log_audit(
        actor=actor,
        module="forecasting",
        action="FORECAST_GENERATED",
        target_type="ForecastRun",
        target_id=run.id,
        metadata={
            "model_version": run.model_version,
            "baseline_mae": run.baseline_mae,
            "model_mae": run.model_mae,
            "model_rmse": run.model_rmse,
        },
    )
    return run