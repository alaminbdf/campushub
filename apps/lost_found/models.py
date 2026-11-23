from __future__ import annotations

import uuid
from django.conf import settings
from django.db import models


class LostFoundReport(models.Model):
    class ReportType(models.TextChoices):
        LOST = "LOST", "Lost Item"
        FOUND = "FOUND", "Found Item"

    class Status(models.TextChoices):
        SUBMITTED = "SUBMITTED", "Submitted (Pending Review)"
        NEEDS_INFO = "NEEDS_INFO", "Clarification Requested"
        ACTIVE = "ACTIVE", "Approved / Active"
        REJECTED = "REJECTED", "Rejected"
        CLOSED_RETURNED = "CLOSED_RETURNED", "Closed (Handed Over)"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    reporter = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="lf_reports"
    )
    report_type = models.CharField(max_length=10, choices=ReportType.choices)
    item_category = models.CharField(max_length=60)
    public_summary = models.CharField(
        max_length=160, help_text="Safe non-identifying summary visible to reviewers."
    )
    private_details = models.TextField(
        help_text="Restricted distinguishing marks used only for ownership verification."
    )
    location = models.CharField(max_length=120)
    status = models.CharField(max_length=24, choices=Status.choices, default=Status.SUBMITTED)
    reviewer_note = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self) -> str:
        return f"[{self.report_type}] {self.item_category} - {self.public_summary}"


class PotentialMatch(models.Model):
    """Explicitly an unverified lead — NEVER proof of ownership (BR-LF-01)."""

    lost_report = models.ForeignKey(
        LostFoundReport, on_delete=models.CASCADE, related_name="lost_matches"
    )
    found_report = models.ForeignKey(
        LostFoundReport, on_delete=models.CASCADE, related_name="found_matches"
    )
    rationale = models.CharField(max_length=255)
    is_verified_ownership = models.BooleanField(default=False, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["lost_report", "found_report"], name="uniq_lost_found_pair"
            )
        ]


class OwnershipClaim(models.Model):
    class ClaimStatus(models.TextChoices):
        PENDING = "PENDING", "Pending Verification"
        NEEDS_EVIDENCE = "NEEDS_EVIDENCE", "Additional Evidence Needed"
        VERIFIED = "VERIFIED", "Ownership Verified"
        REJECTED = "REJECTED", "Rejected"
        ESCALATED = "ESCALATED", "Escalated to Security Officer"
        HANDED_OVER = "HANDED_OVER", "Item Handed Over"

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    found_report = models.ForeignKey(
        LostFoundReport, on_delete=models.CASCADE, related_name="claims"
    )
    claimant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="ownership_claims"
    )
    evidence_description = models.TextField()
    status = models.CharField(
        max_length=24, choices=ClaimStatus.choices, default=ClaimStatus.PENDING
    )
    reviewer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="reviewed_claims",
    )
    assigned_security_officer = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="security_cases",
    )
    decision_reason = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]


class ItemHandover(models.Model):
    """Mandatory chain-of-custody record before closing case as returned (BR-LF-03)."""

    claim = models.OneToOneField(
        OwnershipClaim, on_delete=models.PROTECT, related_name="handover_record"
    )
    authorized_staff = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="completed_handovers"
    )
    recipient_verification_note = models.CharField(max_length=255)
    outcome = models.CharField(max_length=120, default="Returned to verified owner")
    handed_over_at = models.DateTimeField(auto_now_add=True)