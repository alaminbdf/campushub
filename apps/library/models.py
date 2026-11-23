from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models
from django.db.models import Q


class LibraryZone(models.Model):
    name = models.CharField(max_length=80, unique=True)
    floor_no = models.PositiveSmallIntegerField(default=1)
    is_closed = models.BooleanField(default=False)
    closure_reason = models.CharField(max_length=255, blank=True)

    def __str__(self) -> str:
        return f"{self.name} (Floor {self.floor_no})"


class LibrarySeat(models.Model):
    zone = models.ForeignKey(LibraryZone, on_delete=models.CASCADE, related_name="seats")
    seat_code = models.CharField(max_length=24, unique=True)
    has_power_outlet = models.BooleanField(default=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["seat_code"]

    def __str__(self) -> str:
        return f"{self.seat_code} ({self.zone.name})"


class LibrarySession(models.Model):
    session_date = models.DateField(db_index=True)
    slot_order = models.PositiveSmallIntegerField()
    label = models.CharField(max_length=40)
    start_time = models.TimeField()
    end_time = models.TimeField()
    is_closed = models.BooleanField(default=False)

    class Meta:
        ordering = ["session_date", "slot_order"]
        constraints = [
            models.UniqueConstraint(
                fields=["session_date", "slot_order"],
                name="uniq_session_date_slot_order",
            )
        ]

    def __str__(self) -> str:
        return f"{self.session_date} | {self.label}"


class SeatClosure(models.Model):
    seat = models.ForeignKey(LibrarySeat, on_delete=models.CASCADE, related_name="closures")
    session = models.ForeignKey(LibrarySession, on_delete=models.CASCADE, related_name="seat_closures")
    reason = models.CharField(max_length=255)
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["seat", "session"], name="uniq_seat_session_closure")
        ]


class BookingPolicy(models.Model):
    """Prototype defaults (explicitly labeled as prototype assumptions, not DIU policy)."""

    max_consecutive_sessions = models.PositiveSmallIntegerField(default=2)
    allow_multiple_bookings_per_day = models.BooleanField(default=False)
    checkin_grace_minutes = models.PositiveSmallIntegerField(default=15)
    is_active = models.BooleanField(default=True)
    updated_at = models.DateTimeField(auto_now=True)

    @classmethod
    def get_active(cls) -> "BookingPolicy":
        policy = cls.objects.filter(is_active=True).order_by("-updated_at").first()
        return policy or cls.objects.create()


class Reservation(models.Model):
    class BookingType(models.TextChoices):
        INDIVIDUAL = "INDIVIDUAL", "Individual"
        GROUP = "GROUP", "Group"

    class Status(models.TextChoices):
        PENDING_CONSENT = "PENDING_CONSENT", "Pending Attendee Consent"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CANCELLED = "CANCELLED", "Cancelled"
        COMPLETED = "COMPLETED", "Completed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_reservations"
    )
    operational_date = models.DateField(db_index=True)
    booking_type = models.CharField(max_length=16, choices=BookingType.choices)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.CONFIRMED)
    idempotency_key = models.CharField(max_length=64, unique=True, null=True, blank=True)
    override_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="authorized_overrides",
    )
    override_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class AttendeeSessionAllocation(models.Model):
    class ConsentStatus(models.TextChoices):
        NOT_REQUIRED = "NOT_REQUIRED", "Self / Not Required"
        PENDING = "PENDING", "Pending Acceptance"
        ACCEPTED = "ACCEPTED", "Accepted"
        DECLINED = "DECLINED", "Declined"

    class AllocationStatus(models.TextChoices):
        PENDING = "PENDING", "Pending Consent"
        CONFIRMED = "CONFIRMED", "Confirmed"
        CHECKED_IN = "CHECKED_IN", "Checked In"
        NO_SHOW = "NO_SHOW", "No-Show"
        RELEASED = "RELEASED", "Released"
        CANCELLED = "CANCELLED", "Cancelled"

    ACTIVE_STATUSES = (AllocationStatus.CONFIRMED, AllocationStatus.CHECKED_IN)

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reservation = models.ForeignKey(
        Reservation, on_delete=models.CASCADE, related_name="allocations"
    )
    attendee = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="session_allocations"
    )
    seat = models.ForeignKey(LibrarySeat, on_delete=models.PROTECT, related_name="allocations")
    session = models.ForeignKey(LibrarySession, on_delete=models.PROTECT, related_name="allocations")
    consent_status = models.CharField(
        max_length=16, choices=ConsentStatus.choices, default=ConsentStatus.NOT_REQUIRED
    )
    status = models.CharField(
        max_length=16, choices=AllocationStatus.choices, default=AllocationStatus.CONFIRMED
    )
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="recorded_checkins",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["attendee", "session"],
                condition=Q(status__in=["CONFIRMED", "CHECKED_IN"]),
                name="uniq_active_attendee_session",
            ),
            models.UniqueConstraint(
                fields=["seat", "session"],
                condition=Q(status__in=["CONFIRMED", "CHECKED_IN"]),
                name="uniq_active_seat_session",
            ),
        ]