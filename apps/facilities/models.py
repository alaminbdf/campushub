from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models


class FacilityTicket(models.Model):
    class IssueType(models.TextChoices):
        FACILITY = "FACILITY", "Facility Issue"
        EQUIPMENT = "EQUIPMENT", "Equipment Issue"

    class Priority(models.TextChoices):
        LOW = "LOW", "Low"
        MEDIUM = "MEDIUM", "Medium"
        HIGH = "HIGH", "High"

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted"
        UNDER_REVIEW = "UNDER_REVIEW", "Under Review"
        NEEDS_INFO = "NEEDS_INFO", "Awaiting Clarification"
        ASSIGNED = "ASSIGNED", "Assigned"
        IN_PROGRESS = "IN_PROGRESS", "In Progress"
        ESCALATED = "ESCALATED", "Escalated (Specialist)"
        RESOLVED = "RESOLVED", "Resolved"
        REOPENED = "REOPENED", "Reopened"
        CLOSED = "CLOSED", "Closed"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="facility_tickets"
    )
    issue_type = models.CharField(max_length=16, choices=IssueType.choices)
    category = models.CharField(max_length=64)
    location = models.CharField(max_length=120)
    description = models.TextField()
    priority = models.CharField(max_length=12, choices=Priority.choices, default=Priority.MEDIUM)
    status = models.CharField(max_length=20, choices=Status.choices, default=Status.SUBMITTED)
    assigned_to = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="assigned_tickets",
    )
    resolution_notes = models.TextField(blank=True)
    reopen_count = models.PositiveSmallIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"[{self.status}] {self.category} @ {self.location}"


class TicketTransition(models.Model):
    """Full status history with actor and timestamp (FR-UT-13, BR-UT-03)."""

    ticket = models.ForeignKey(
        FacilityTicket, on_delete=models.CASCADE, related_name="transitions"
    )
    from_status = models.CharField(max_length=20)
    to_status = models.CharField(max_length=20)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["created_at"]