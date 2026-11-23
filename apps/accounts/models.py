from __future__ import annotations

import uuid
from typing import Any
from django.contrib.auth.models import AbstractUser
from django.core.exceptions import PermissionDenied
from django.db import models


class OperationalRole(models.TextChoices):
    """Exact 9 operational roles in the CampusHub SRS baseline (no Faculty role)."""

    STUDENT = "STUDENT", "Student"
    LIBRARY_STAFF = "LIBRARY_STAFF", "Library Staff"
    LIBRARY_SUPERVISOR = "LIBRARY_SUPERVISOR", "Library Supervisor"
    LF_REVIEWER = "LF_REVIEWER", "Lost and Found Reviewer"
    SECURITY_OFFICER = "SECURITY_OFFICER", "Security Officer"
    IT_STAFF = "IT_STAFF", "IT Staff"
    UTILITY_STAFF = "UTILITY_STAFF", "Utility Staff"
    MANAGEMENT_OFFICER = "MANAGEMENT_OFFICER", "Management Officer"
    SYSTEM_ADMIN = "SYSTEM_ADMIN", "System Administrator"


class User(AbstractUser):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    institutional_id = models.CharField(max_length=32, unique=True)
    role = models.CharField(
        max_length=32,
        choices=OperationalRole.choices,
        default=OperationalRole.STUDENT,
        db_index=True,
    )

    def __str__(self) -> str:
        return f"{self.institutional_id} ({self.get_role_display()})"


class AuditEvent(models.Model):
    """Immutable append-only audit trail (FR-ADM-04, NFR-SEC-03)."""

    id = models.BigAutoField(primary_key=True)
    actor = models.ForeignKey(
        User, on_delete=models.PROTECT, null=True, blank=True, related_name="audit_events"
    )
    module = models.CharField(max_length=40, db_index=True)
    action = models.CharField(max_length=64, db_index=True)
    target_type = models.CharField(max_length=64)
    target_id = models.CharField(max_length=64)
    reason = models.TextField(blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-created_at"]

    def save(self, *args: Any, **kwargs: Any) -> None:
        if self.pk is not None:
            raise PermissionDenied("AuditEvent records are immutable.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise PermissionDenied("AuditEvent records cannot be deleted.")


def log_audit(
    *,
    actor: User | None,
    module: str,
    action: str,
    target_type: str,
    target_id: Any,
    reason: str = "",
    metadata: dict[str, Any] | None = None,
) -> AuditEvent:
    return AuditEvent.objects.create(
        actor=actor,
        module=module,
        action=action,
        target_type=target_type,
        target_id=str(target_id),
        reason=reason,
        metadata=metadata or {},
    )