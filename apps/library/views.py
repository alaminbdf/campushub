from __future__ import annotations

from datetime import date
import uuid
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import OperationalRole, User, log_audit
from apps.accounts.permissions import role_required
from apps.library.models import (
    AttendeeSessionAllocation,
    BookingPolicy,
    LibrarySeat,
    LibrarySession,
    LibraryZone,
    Reservation,
    SeatClosure,
)
from apps.library.services import (
    AllocationRequestItem,
    cancel_reservation,
    check_in_allocation,
    create_reservation,
    release_expired_no_shows,
    respond_to_group_invitation,
)


@role_required(
    OperationalRole.STUDENT,
    OperationalRole.LIBRARY_STAFF,
    OperationalRole.LIBRARY_SUPERVISOR,
    OperationalRole.MANAGEMENT_OFFICER,
    OperationalRole.SYSTEM_ADMIN,
)
def index_view(request: HttpRequest) -> HttpResponse:
    date_str = request.GET.get("date")
    try:
        selected_date = date.fromisoformat(date_str) if date_str else date.today()
    except ValueError:
        selected_date = date.today()

    sessions = list(LibrarySession.objects.filter(session_date=selected_date).order_by("slot_order"))
    seats = list(LibrarySeat.objects.select_related("zone").filter(is_active=True).order_by("zone__name", "seat_code"))
    zones = list(LibraryZone.objects.all().order_by("floor_no", "name"))
    policy = BookingPolicy.get_active()

    active_allocs = AttendeeSessionAllocation.objects.filter(
        session__session_date=selected_date,
        status__in=AttendeeSessionAllocation.ACTIVE_STATUSES,
    ).values_list("seat_id", "session_id")
    booked_pairs = set(active_allocs)

    closed_pairs = set(
        SeatClosure.objects.filter(session__session_date=selected_date).values_list("seat_id", "session_id")
    )

    availability_rows = []
    for seat in seats:
        slot_states = []
        for sess in sessions:
            if seat.zone.is_closed or sess.is_closed or (seat.id, sess.id) in closed_pairs:
                state = "CLOSED"
            elif (seat.id, sess.id) in booked_pairs:
                state = "BOOKED"
            else:
                state = "AVAILABLE"
            slot_states.append({"session": sess, "state": state})
        availability_rows.append({"seat": seat, "slots": slot_states})

    user = request.user
    if user.role == OperationalRole.STUDENT:
        my_allocations = (
            AttendeeSessionAllocation.objects.select_related("reservation", "seat", "seat__zone", "session", "attendee")
            .filter(Q(attendee=user) | Q(reservation__creator=user))
            .order_by("-created_at")[:25]
        )
        pending_invites = (
            Reservation.objects.filter(
                status=Reservation.Status.PENDING_CONSENT,
                allocations__attendee=user,
                allocations__consent_status=AttendeeSessionAllocation.ConsentStatus.PENDING,
            )
            .distinct()
            .prefetch_related("allocations__seat", "allocations__session", "allocations__attendee")
        )
        duty_allocations = []
    else:
        my_allocations = []
        pending_invites = []
        duty_allocations = (
            AttendeeSessionAllocation.objects.select_related("reservation", "seat", "session", "attendee")
            .filter(session__session_date=selected_date)
            .order_by("session__slot_order", "seat__seat_code")
        )

    other_students = User.objects.filter(role=OperationalRole.STUDENT, is_active=True).exclude(id=user.id)

    context = {
        "selected_date": selected_date,
        "available_dates": sorted(set(LibrarySession.objects.values_list("session_date", flat=True))),
        "sessions": sessions,
        "seats": seats,
        "zones": zones,
        "policy": policy,
        "availability_rows": availability_rows,
        "my_allocations": my_allocations,
        "pending_invites": pending_invites,
        "duty_allocations": duty_allocations,
        "other_students": other_students,
        "idempotency_token": str(uuid.uuid4()),
    }
    return render(request, "library/index.html", context)


@require_POST
@role_required(OperationalRole.STUDENT)
def book_individual_view(request: HttpRequest) -> HttpResponse:
    op_date = date.fromisoformat(request.POST["operational_date"])
    seat_id = int(request.POST["seat_id"])
    session_ids = [int(sid) for sid in request.POST.getlist("session_ids")]
    idem_key = request.POST.get("idempotency_key") or None

    items = [
        AllocationRequestItem(attendee_id=request.user.id, seat_id=seat_id, session_id=sid)
        for sid in session_ids
    ]
    try:
        res = create_reservation(
            creator=request.user,
            operational_date=op_date,
            items=items,
            idempotency_key=idem_key,
        )
        messages.success(request, f"Individual reservation confirmed (ID: {str(res.id)[:8]}).")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))

    return redirect(f"/library/?date={op_date.isoformat()}")


@require_POST
@role_required(OperationalRole.STUDENT)
def book_group_view(request: HttpRequest) -> HttpResponse:
    op_date = date.fromisoformat(request.POST["operational_date"])
    creator_seat_id = int(request.POST["creator_seat_id"])
    creator_session_ids = [int(sid) for sid in request.POST.getlist("creator_session_ids")]

    invitee_inst_id = request.POST.get("invitee_institutional_id", "").strip()
    invitee_seat_id = int(request.POST["invitee_seat_id"])
    invitee_session_ids = [int(sid) for sid in request.POST.getlist("invitee_session_ids")]

    invitee = User.objects.filter(institutional_id=invitee_inst_id, role=OperationalRole.STUDENT).first()
    if not invitee or invitee.id == request.user.id:
        messages.error(request, "Please select a valid different student to invite.")
        return redirect(f"/library/?date={op_date.isoformat()}")

    items = [
        AllocationRequestItem(attendee_id=request.user.id, seat_id=creator_seat_id, session_id=sid)
        for sid in creator_session_ids
    ] + [
        AllocationRequestItem(attendee_id=invitee.id, seat_id=invitee_seat_id, session_id=sid)
        for sid in invitee_session_ids
    ]

    try:
        res = create_reservation(
            creator=request.user,
            operational_date=op_date,
            items=items,
            idempotency_key=request.POST.get("idempotency_key") or None,
        )
        messages.success(
            request,
            f"Group reservation created (ID: {str(res.id)[:8]}) — status: {res.get_status_display()}. "
            f"Waiting for {invitee.institutional_id} to accept.",
        )
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))

    return redirect(f"/library/?date={op_date.isoformat()}")


@require_POST
@role_required(OperationalRole.STUDENT)
def respond_invite_view(request: HttpRequest, reservation_id: uuid.UUID) -> HttpResponse:
    accept = request.POST.get("decision") == "accept"
    try:
        res = respond_to_group_invitation(
            attendee=request.user, reservation_id=reservation_id, accept=accept
        )
        messages.success(request, f"Invitation response saved. Reservation status: {res.get_status_display()}.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    return redirect("library:index")


@require_POST
@role_required(OperationalRole.STUDENT, OperationalRole.LIBRARY_STAFF, OperationalRole.LIBRARY_SUPERVISOR)
def cancel_reservation_view(request: HttpRequest, reservation_id: uuid.UUID) -> HttpResponse:
    try:
        cancel_reservation(
            actor=request.user,
            reservation_id=reservation_id,
            reason=request.POST.get("reason", "User requested cancellation"),
        )
        messages.success(request, "Reservation cancelled and history recorded.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, str(exc))
    return redirect("library:index")


@require_POST
@role_required(OperationalRole.STUDENT, OperationalRole.LIBRARY_STAFF, OperationalRole.LIBRARY_SUPERVISOR)
def checkin_view(request: HttpRequest, allocation_id: uuid.UUID) -> HttpResponse:
    try:
        check_in_allocation(actor=request.user, allocation_id=allocation_id)
        messages.success(request, "Check-in recorded.")
    except (ValidationError, PermissionDenied) as exc:
        messages.error(request, "; ".join(exc.messages) if hasattr(exc, "messages") else str(exc))
    return redirect("library:index")


@require_POST
@role_required(OperationalRole.LIBRARY_STAFF, OperationalRole.LIBRARY_SUPERVISOR)
def release_noshows_view(request: HttpRequest) -> HttpResponse:
    count = release_expired_no_shows(actor=request.user)
    messages.info(request, f"No-show sweep complete: {count} expired allocation(s) released.")
    return redirect("library:index")


@require_POST
@role_required(OperationalRole.LIBRARY_STAFF, OperationalRole.LIBRARY_SUPERVISOR)
def close_seat_view(request: HttpRequest) -> HttpResponse:
    seat = get_object_or_404(LibrarySeat, id=request.POST["seat_id"])
    session = get_object_or_404(LibrarySession, id=request.POST["session_id"])
    reason = request.POST.get("reason", "").strip() or "Temporary operational maintenance"
    SeatClosure.objects.get_or_create(
        seat=seat,
        session=session,
        defaults={"reason": reason, "closed_by": request.user},
    )
    log_audit(
        actor=request.user,
        module="library",
        action="SEAT_CLOSED_TEMPORARILY",
        target_type="LibrarySeat",
        target_id=seat.id,
        reason=reason,
        metadata={"session_id": session.id},
    )
    messages.warning(request, f"Seat {seat.seat_code} closed for {session.label}.")
    return redirect(f"/library/?date={session.session_date.isoformat()}")