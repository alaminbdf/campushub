from __future__ import annotations

import json
from django.contrib import messages
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import OperationalRole
from apps.accounts.permissions import role_required
from apps.forecasting.ml_pipeline import run_demand_forecast
from apps.forecasting.models import ForecastRun
from apps.library.models import AttendeeSessionAllocation


@role_required(
    OperationalRole.STUDENT,
    OperationalRole.LIBRARY_STAFF,
    OperationalRole.LIBRARY_SUPERVISOR,
    OperationalRole.MANAGEMENT_OFFICER,
    OperationalRole.IT_STAFF,
    OperationalRole.SYSTEM_ADMIN,
)
def index_view(request: HttpRequest) -> HttpResponse:
    latest_run = ForecastRun.objects.prefetch_related("predictions__zone").first()
    rows = []
    labels = []
    predicted_vals = []
    capacity_vals = []

    if latest_run:
        # Compute live confirmed occupancy separately so forecasts are never confused with live counts
        for pred in latest_run.predictions.all()[:16]:
            live_booked = AttendeeSessionAllocation.objects.filter(
                seat__zone=pred.zone,
                session__session_date=pred.target_date,
                session__slot_order=pred.slot_order,
                status__in=AttendeeSessionAllocation.ACTIVE_STATUSES,
            ).count()
            live_available = max(pred.configured_capacity - live_booked, 0)
            rows.append(
                {
                    "pred": pred,
                    "live_booked": live_booked,
                    "live_available": live_available,
                }
            )
            labels.append(f"{pred.target_date.strftime('%b %d')} S{pred.slot_order} ({pred.zone.name[:8]})")
            predicted_vals.append(pred.predicted_demand)
            capacity_vals.append(pred.configured_capacity)

    can_trigger = request.user.role in {
        OperationalRole.LIBRARY_SUPERVISOR,
        OperationalRole.MANAGEMENT_OFFICER,
        OperationalRole.IT_STAFF,
        OperationalRole.SYSTEM_ADMIN,
    }
    context = {
        "latest_run": latest_run,
        "rows": rows,
        "can_trigger": can_trigger,
        "chart_labels_json": json.dumps(labels),
        "chart_predicted_json": json.dumps(predicted_vals),
        "chart_capacity_json": json.dumps(capacity_vals),
    }
    return render(request, "forecasting/index.html", context)


@require_POST
@role_required(
    OperationalRole.LIBRARY_SUPERVISOR,
    OperationalRole.MANAGEMENT_OFFICER,
    OperationalRole.IT_STAFF,
    OperationalRole.SYSTEM_ADMIN,
)
def generate_forecast_view(request: HttpRequest) -> HttpResponse:
    run = run_demand_forecast(actor=request.user, horizon_days=3)
    messages.success(
        request,
        f"Forecast updated ({run.model_version}) — Model MAE: {run.model_mae} vs Baseline MAE: {run.baseline_mae}.",
    )
    return redirect("forecasting:index")