from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.db import connection
from django.http import HttpRequest, HttpResponse, JsonResponse
from django.shortcuts import render

from apps.accounts.models import AuditEvent, OperationalRole, User
from apps.facilities.models import FacilityTicket
from apps.forecasting.models import ForecastRun
from apps.library.models import AttendeeSessionAllocation, LibrarySeat, Reservation
from apps.lost_found.models import LostFoundReport, OwnershipClaim


@login_required
def home_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    stats: dict[str, int | str] = {}

    if user.role == OperationalRole.STUDENT:
        stats = {
            "My Active Allocations": AttendeeSessionAllocation.objects.filter(
                attendee=user, status__in=AttendeeSessionAllocation.ACTIVE_STATUSES
            ).count(),
            "Pending Group Invites": AttendeeSessionAllocation.objects.filter(
                attendee=user, consent_status=AttendeeSessionAllocation.ConsentStatus.PENDING
            ).count(),
            "My Lost & Found Reports": LostFoundReport.objects.filter(reporter=user).count(),
            "My Facility Tickets": FacilityTicket.objects.filter(reporter=user).count(),
        }
    elif user.role == OperationalRole.SECURITY_OFFICER:
        stats = {
            "Assigned Escalated Cases": OwnershipClaim.objects.filter(
                assigned_security_officer=user
            ).count(),
        }
    else:
        stats = {
            "Active Library Seats": LibrarySeat.objects.filter(is_active=True).count(),
            "Confirmed Reservations": Reservation.objects.filter(
                status=Reservation.Status.CONFIRMED
            ).count(),
            "Open L&F Reports": LostFoundReport.objects.exclude(
                status=LostFoundReport.Status.CLOSED_RETURNED
            ).count(),
            "Open Facility Tickets": FacilityTicket.objects.exclude(
                status__in=[FacilityTicket.Status.RESOLVED, FacilityTicket.Status.CLOSED]
            ).count(),
            "Registered Users": User.objects.filter(is_active=True).count(),
        }

    recent_audit = (
        AuditEvent.objects.select_related("actor")[:10]
        if user.role in {
            OperationalRole.SYSTEM_ADMIN,
            OperationalRole.LIBRARY_SUPERVISOR,
            OperationalRole.MANAGEMENT_OFFICER,
            OperationalRole.IT_STAFF,
        }
        else []
    )

    context = {
        "stats": stats,
        "latest_forecast": ForecastRun.objects.first(),
        "recent_audit": recent_audit,
    }
    return render(request, "dashboards/home.html", context)


def health_view(request: HttpRequest) -> JsonResponse:
    with connection.cursor() as cursor:
        cursor.execute("SELECT 1")
    return JsonResponse({"status": "ok", "service": "CampusHub Prototype"})