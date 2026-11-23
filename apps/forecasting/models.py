from __future__ import annotations

import uuid
from django.db import models
from apps.library.models import LibraryZone


class ForecastRun(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    model_version = models.CharField(max_length=48)
    algorithm = models.CharField(max_length=80)
    target_metric = models.CharField(max_length=80, default="Aggregate session seat demand")
    horizon_days = models.PositiveSmallIntegerField(default=3)
    is_synthetic_data = models.BooleanField(default=True)
    baseline_mae = models.FloatField()
    model_mae = models.FloatField()
    model_rmse = models.FloatField()
    caveat_notice = models.TextField(
        default=(
            "ESTIMATE ONLY — NOT GUARANTEED LIVE SEAT AVAILABILITY. "
            "Trained on clearly labeled synthetic prototype data pending authorized DIU history."
        )
    )
    generated_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-generated_at"]


class ForecastPrediction(models.Model):
    run = models.ForeignKey(ForecastRun, on_delete=models.CASCADE, related_name="predictions")
    zone = models.ForeignKey(LibraryZone, on_delete=models.CASCADE, related_name="forecasts")
    target_date = models.DateField(db_index=True)
    slot_order = models.PositiveSmallIntegerField()
    slot_label = models.CharField(max_length=40)
    predicted_demand = models.FloatField()
    configured_capacity = models.PositiveIntegerField()

    class Meta:
        ordering = ["target_date", "slot_order", "zone_id"]