from django.urls import path
from apps.lost_found import views

app_name = "lost_found"

urlpatterns = [
    path("", views.index_view, name="index"),
    path("report/", views.submit_report_view, name="submit_report"),
    path("report/<uuid:report_id>/review/", views.review_report_view, name="review_report"),
    path("match/suggest/", views.suggest_match_view, name="suggest_match"),
    path("claim/submit/", views.submit_claim_view, name="submit_claim"),
    path("claim/<uuid:claim_id>/decide/", views.decide_claim_view, name="decide_claim"),
    path("claim/<uuid:claim_id>/handover/", views.record_handover_view, name="record_handover"),
]