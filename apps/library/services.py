from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from uuid import UUID

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.accounts.models import OperationalRole, User, log_audit
from apps.library.models import (
    AttendeeSessionAllocation,
    BookingPolicy,
    LibrarySeat,
    LibrarySession,
    Reservation,
    SeatClosure,
)


@dataclass(frozen=True)
class AllocationRequestItem:
    attendee_id: UUID
    seat_id: int
    session_id: int


def _validate_attendee_limits(
    *,
    attendee: User,
    requested_sessions: list[LibrarySession],
    operational_date: date,
    policy: BookingPolicy,
    exclude_reservation_id: UUID | None = None,
) -> None:
    """Enforces BR-LIB-03, BR-LIB-04, BR-LIB-05 across ALL reservation creators."""
    existing_qs = AttendeeSessionAllocation.objects.filter(
        attendee=attendee,
        session__session_date=operational_date,
        status__in=AttendeeSessionAllocation.ACTIVE_STATUSES,
    )
    if exclude_reservation_id:
        existing_qs = existing_qs.exclude(reservation_id=exclude_reservation_id)

    if existing_qs.exists() and not policy.allow_multiple_bookings_per_day:
        raise ValidationError(
            f"{attendee.institutional_id} already has a confirmed booking on {operational_date} "
            "(daily limit applies across all creators)."
        )

    req_slots = sorted({s.slot_order for s in requested_sessions})
    if len(req_slots) != len(requested_sessions):
        raise ValidationError(f"Duplicate session requested for {attendee.institutional_id}.")

    if len(req_slots) > policy.max_consecutive_sessions:
        raise ValidationError(
            f"{attendee.institutional_id} exceeds the maximum of "
            f"{policy.max_consecutive_sessions} consecutive sessions."
        )

    for prev_slot, next_slot in zip(req_slots, req_slots[1:]):
        if next_slot - prev_slot != 1:
            raise ValidationError(
                f"Requested sessions for {attendee.institutional_id} must be consecutive."
            )


def create_reservation(
    *,
    creator: User,
    operational_date: date,
    items: list[AllocationRequestItem],
    idempotency_key: str | None = None,
    supervisor_override_by: User | None = None,
    override_reason: str = "",
) -> Reservation:
    """
    Corrected concurrency protocol:
    1. Lock all attendee identity rows in ascending UUID order.
    2. Lock session and seat rows in ascending ID order.
    3. Re-read active allocations across all creators and revalidate limits/capacity.
    4. Commit reservation, allocations, and audit log atomically.
    """
    if creator.role != OperationalRole.STUDENT and supervisor_override_by is None:
        raise PermissionDenied("Only students can create reservations.")
    if not items:
        raise ValidationError("Select at least one seat and session.")

    if idempotency_key:
        existing = Reservation.objects.filter(idempotency_key=idempotency_key).first()
        if existing:
            return existing

    policy = BookingPolicy.get_active()
    attendee_ids = sorted({i.attendee_id for i in items})
    session_ids = sorted({i.session_id for i in items})
    seat_ids = sorted({i.seat_id for i in items})
    is_group = len(attendee_ids) > 1 or any(uid != creator.id for uid in attendee_ids)

    try:
        with transaction.atomic():
            locked_users = {
                u.id: u
                for u in User.objects.select_for_update().filter(id__in=attendee_ids).order_by("id")
            }
            if len(locked_users) != len(attendee_ids):
                raise ValidationError("One or more attendee IDs could not be found.")
            for u in locked_users.values():
                if not u.is_active or u.role != OperationalRole.STUDENT:
                    raise ValidationError(f"{u.institutional_id} is not an eligible active student.")

            locked_sessions = {
                s.id: s
                for s in LibrarySession.objects.select_for_update()
                .filter(id__in=session_ids)
                .order_by("id")
            }
            locked_seats = {
                st.id: st
                for st in LibrarySeat.objects.select_for_update()
                .select_related("zone")
                .filter(id__in=seat_ids)
                .order_by("id")
            }

            for item in items:
                session = locked_sessions[item.session_id]
                seat = locked_seats[item.seat_id]
                if session.session_date != operational_date:
                    raise ValidationError("All sessions must belong to the chosen date.")
                if session.is_closed or not seat.is_active or seat.zone.is_closed:
                    raise ValidationError(f"Seat {seat.seat_code} or session {session.label} is closed.")
                if SeatClosure.objects.filter(seat=seat, session=session).exists():
                    raise ValidationError(f"Seat {seat.seat_code} is temporarily closed for {session.label}.")

            if supervisor_override_by is None:
                by_attendee: dict[UUID, list[LibrarySession]] = {}
                for item in items:
                    by_attendee.setdefault(item.attendee_id, []).append(locked_sessions[item.session_id])
                for aid, req_sessions in by_attendee.items():
                    _validate_attendee_limits(
                        attendee=locked_users[aid],
                        requested_sessions=req_sessions,
                        operational_date=operational_date,
                        policy=policy,
                    )
            else:
                if supervisor_override_by.role != OperationalRole.LIBRARY_SUPERVISOR:
                    raise PermissionDenied("Only a Library Supervisor may authorize an override.")
                if not override_reason.strip():
                    raise ValidationError("Supervisor override requires a documented reason.")

            seen_pairs: set[tuple[int, int]] = set()
            for item in items:
                pair = (item.seat_id, item.session_id)
                if pair in seen_pairs:
                    raise ValidationError("Cannot assign two attendees to the same seat and session.")
                seen_pairs.add(pair)
                if AttendeeSessionAllocation.objects.filter(
                    seat_id=item.seat_id,
                    session_id=item.session_id,
                    status__in=AttendeeSessionAllocation.ACTIVE_STATUSES,
                ).exists():
                    raise ValidationError(
                        f"Seat {locked_seats[item.seat_id].seat_code} is already taken for "
                        f"{locked_sessions[item.session_id].label}."
                    )

            has_other_invitees = any(i.attendee_id != creator.id for i in items)
            res_status = (
                Reservation.Status.PENDING_CONSENT
                if (is_group and has_other_invitees and supervisor_override_by is None)
                else Reservation.Status.CONFIRMED
            )

            reservation = Reservation.objects.create(
                creator=creator,
                operational_date=operational_date,
                booking_type=Reservation.BookingType.GROUP if is_group else Reservation.BookingType.INDIVIDUAL,
                status=res_status,
                idempotency_key=idempotency_key,
                override_by=supervisor_override_by,
                override_reason=override_reason,
            )

            for item in items:
                needs_consent = item.attendee_id != creator.id and supervisor_override_by is None
                AttendeeSessionAllocation.objects.create(
                    reservation=reservation,
                    attendee_id=item.attendee_id,
                    seat_id=item.seat_id,
                    session_id=item.session_id,
                    consent_status=(
                        AttendeeSessionAllocation.ConsentStatus.PENDING
                        if needs_consent
                        else AttendeeSessionAllocation.ConsentStatus.NOT_REQUIRED
                    ),
                    status=(
                        AttendeeSessionAllocation.AllocationStatus.PENDING
                        if res_status == Reservation.Status.PENDING_CONSENT
                        else AttendeeSessionAllocation.AllocationStatus.CONFIRMED
                    ),
                )

            log_audit(
                actor=supervisor_override_by or creator,
                module="library",
                action="RESERVATION_OVERRIDE" if supervisor_override_by else "RESERVATION_CREATED",
                target_type="Reservation",
                target_id=reservation.id,
                reason=override_reason,
                metadata={"type": reservation.booking_type, "status": reservation.status},
            )
            return reservation
    except IntegrityError as exc:
        raise ValidationError("Concurrent booking conflict detected. Please refresh.") from exc


def respond_to_group_invitation(*, attendee: User, reservation_id: UUID, accept: bool) -> Reservation:
    policy = BookingPolicy.get_active()
    with transaction.atomic():
        reservation = Reservation.objects.select_for_update().get(id=reservation_id)
        allocs = list(reservation.allocations.select_related("session", "seat", "attendee"))
        mine = [a for a in allocs if a.attendee_id == attendee.id]
        if not mine:
            raise PermissionDenied("You are not invited to this reservation.")
        if reservation.status != Reservation.Status.PENDING_CONSENT:
            raise ValidationError("Reservation is no longer pending consent.")

        if not accept:
            for a in allocs:
                if a.attendee_id == attendee.id:
                    a.consent_status = AttendeeSessionAllocation.ConsentStatus.DECLINED
                a.status = AttendeeSessionAllocation.AllocationStatus.CANCELLED
                a.save(update_fields=["consent_status", "status"])
            reservation.status = Reservation.Status.CANCELLED
            reservation.save(update_fields=["status"])
            log_audit(
                actor=attendee,
                module="library",
                action="GROUP_INVITE_DECLINED",
                target_type="Reservation",
                target_id=reservation.id,
            )
            return reservation

        for a in mine:
            a.consent_status = AttendeeSessionAllocation.ConsentStatus.ACCEPTED
            a.save(update_fields=["consent_status"])

        if not any(a.consent_status == AttendeeSessionAllocation.ConsentStatus.PENDING for a in allocs):
            attendee_ids = sorted({a.attendee_id for a in allocs})
            session_ids = sorted({a.session_id for a in allocs})
            seat_ids = sorted({a.seat_id for a in allocs})

            locked_users = {
                u.id: u
                for u in User.objects.select_for_update().filter(id__in=attendee_ids).order_by("id")
            }
            list(LibrarySession.objects.select_for_update().filter(id__in=session_ids).order_by("id"))
            list(LibrarySeat.objects.select_for_update().filter(id__in=seat_ids).order_by("id"))

            by_attendee: dict[UUID, list[LibrarySession]] = {}
            for a in allocs:
                by_attendee.setdefault(a.attendee_id, []).append(a.session)
                if AttendeeSessionAllocation.objects.filter(
                    seat_id=a.seat_id,
                    session_id=a.session_id,
                    status__in=AttendeeSessionAllocation.ACTIVE_STATUSES,
                ).exists():
                    raise ValidationError(f"Seat {a.seat.seat_code} was taken before group confirmation.")

            for aid, req_sessions in by_attendee.items():
                _validate_attendee_limits(
                    attendee=locked_users[aid],
                    requested_sessions=req_sessions,
                    operational_date=reservation.operational_date,
                    policy=policy,
                    exclude_reservation_id=reservation.id,
                )

            for a in allocs:
                a.status = AttendeeSessionAllocation.AllocationStatus.CONFIRMED
                a.save(update_fields=["status"])
            reservation.status = Reservation.Status.CONFIRMED
            reservation.save(update_fields=["status"])
            log_audit(
                actor=attendee,
                module="library",
                action="GROUP_RESERVATION_CONFIRMED",
                target_type="Reservation",
                target_id=reservation.id,
            )
        return reservation


def cancel_reservation(*, actor: User, reservation_id: UUID, reason: str = "") -> Reservation:
    with transaction.atomic():
        reservation = Reservation.objects.select_for_update().get(id=reservation_id)
        is_allowed = (
            reservation.creator_id == actor.id
            or actor.role in {OperationalRole.LIBRARY_STAFF, OperationalRole.LIBRARY_SUPERVISOR}
        )
        if not is_allowed:
            raise PermissionDenied("Not authorized to cancel this reservation.")
        if reservation.status == Reservation.Status.CANCELLED:
            return reservation

        reservation.status = Reservation.Status.CANCELLED
        reservation.save(update_fields=["status"])
        reservation.allocations.filter(
            status__in=[
                AttendeeSessionAllocation.AllocationStatus.PENDING,
                AttendeeSessionAllocation.AllocationStatus.CONFIRMED,
            ]
        ).update(status=AttendeeSessionAllocation.AllocationStatus.CANCELLED)

        log_audit(
            actor=actor,
            module="library",
            action="RESERVATION_CANCELLED",
            target_type="Reservation",
            target_id=reservation.id,
            reason=reason,
        )
        return reservation


def check_in_allocation(*, actor: User, allocation_id: UUID) -> AttendeeSessionAllocation:
    with transaction.atomic():
        alloc = AttendeeSessionAllocation.objects.select_for_update().get(id=allocation_id)
        is_allowed = (
            actor.id == alloc.attendee_id
            or actor.role in {OperationalRole.LIBRARY_STAFF, OperationalRole.LIBRARY_SUPERVISOR}
        )
        if not is_allowed:
            raise PermissionDenied("Not authorized to check in this allocation.")
        if alloc.status != AttendeeSessionAllocation.AllocationStatus.CONFIRMED:
            raise ValidationError("Only confirmed allocations can be checked in.")

        alloc.status = AttendeeSessionAllocation.AllocationStatus.CHECKED_IN
        alloc.checked_in_at = timezone.now()
        alloc.checked_in_by = actor
        alloc.save(update_fields=["status", "checked_in_at", "checked_in_by"])
        log_audit(
            actor=actor,
            module="library",
            action="ATTENDEE_CHECKED_IN",
            target_type="AttendeeSessionAllocation",
            target_id=alloc.id,
        )
        return alloc


def release_expired_no_shows(*, actor: User | None = None, now: datetime | None = None) -> int:
    policy = BookingPolicy.get_active()
    current_time = now or timezone.localtime()
    released = 0
    with transaction.atomic():
        candidates = (
            AttendeeSessionAllocation.objects.select_for_update()
            .select_related("session")
            .filter(status=AttendeeSessionAllocation.AllocationStatus.CONFIRMED)
        )
        for alloc in candidates:
            start_dt = timezone.make_aware(
                datetime.combine(alloc.session.session_date, alloc.session.start_time)
            )
            if current_time > start_dt + timedelta(minutes=policy.checkin_grace_minutes):
                alloc.status = AttendeeSessionAllocation.AllocationStatus.RELEASED
                alloc.save(update_fields=["status"])
                log_audit(
                    actor=actor,
                    module="library",
                    action="NO_SHOW_RELEASED",
                    target_type="AttendeeSessionAllocation",
                    target_id=alloc.id,
                    reason=f"Grace period ({policy.checkin_grace_minutes} min) elapsed.",
                )
                released += 1
    return released