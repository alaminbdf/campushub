from django.urls import path
from apps.library import views

app_name = "library"

urlpatterns = [
    path("", views.index_view, name="index"),
    path("book/individual/", views.book_individual_view, name="book_individual"),
    path("book/group/", views.book_group_view, name="book_group"),
    path("invite/<uuid:reservation_id>/respond/", views.respond_invite_view, name="respond_invite"),
    path("reservation/<uuid:reservation_id>/cancel/", views.cancel_reservation_view, name="cancel"),
    path("allocation/<uuid:allocation_id>/checkin/", views.checkin_view, name="checkin"),
    path("ops/release-noshows/", views.release_noshows_view, name="release_noshows"),
    path("ops/close-seat/", views.close_seat_view, name="close_seat"),
]