from django.urls import path
from apps.forecasting import views

app_name = "forecasting"

urlpatterns = [
    path("", views.index_view, name="index"),
    path("generate/", views.generate_forecast_view, name="generate"),
]