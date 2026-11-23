from django.urls import path
from apps.facilities import views

app_name = "facilities"

urlpatterns = [
    path("", views.index_view, name="index"),
    path("submit/", views.submit_ticket_view, name="submit_ticket"),
    path("<uuid:ticket_id>/update/", views.update_ticket_view, name="update_ticket"),
]