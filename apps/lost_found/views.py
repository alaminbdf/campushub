from __future__ import annotations

import uuid
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import OperationalRole, User, log_audit
from apps.accounts.permissions import role_required
from apps.lost_found.models import ItemHandover, LostFoundReport, OwnershipClaim, PotentialMatch


@role_required(
    OperationalRole.STUDENT,
    OperationalRole.LF_REVIEWER,
    OperationalRole.SECURITY_OFFICER,
    OperationalRole.MANAGEMENT_OFFICER,
)
def index_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    if user.role == OperationalRole.STUDENT:
        my_reports = LostFoundReport.objects.filter(reporter=user)
        # Privacy (FR-LF-12): students only see public_summary of active found items, never private_details
        active_found_items = LostFoundReport.objects.filter(
            report_type=LostFoundReport.ReportType.FOUND,
            status=LostFoundReport.Status.ACTIVE,
        )
        claims = OwnershipClaim.objects.select_related("found_report").filter(claimant=user)
        all_reports = []
        matches = []
    elif user.role == OperationalRole.SECURITY_OFFICER:
        # Scoped access: Security Officer sees ONLY escalated cases assigned to them
        my_reports = []
        active_found_items = []
        all_reports = []
        matches = []
        claims = OwnershipClaim.objects.select_related(
            "found_report", "claimant", "reviewer"
        ).filter(assigned_security_officer=user)
    else:
        my_reports = []
        active_found_items = LostFoundReport.objects.filter(
            report_type=LostFoundReport.ReportType.FOUND, status=LostFoundReport.Status.ACTIVE
        )
        all_reports = LostFoundReport.objects.select_related("reporter").all()
        matches = PotentialMatch.objects.select_related("lost_report", "found_report").all()
        claims = OwnershipClaim.objects.select_related(
            "found_report", "claimant", "reviewer", "assigned_security_officer"
        ).all()

    context = {
        "my_reports": my_reports,
        "active_found_items": active_found_items,
        "all_reports": all_reports,
        "lost_reports": LostFoundReport.objects.filter(report_type=LostFoundReport.ReportType.LOST),
        "found_reports": LostFoundReport.objects.filter(report_type=LostFoundReport.ReportType.FOUND),
        "matches": matches,
        "claims": claims,
        "security_officers": User.objects.filter(role=OperationalRole.SECURITY_OFFICER, is_active=True),
    }
    return render(request, "lost_found/index.html", context)


@require_POST
@role_required(OperationalRole.STUDENT)
def submit_report_view(request: HttpRequest) -> HttpResponse:
    report = LostFoundReport.objects.create(
        reporter=request.user,
        report_type=request.POST["report_type"],
        item_category=request.POST["item_category"].strip(),
        public_summary=request.POST["public_summary"].strip(),
        private_details=request.POST["private_details"].strip(),
        location=request.POST["location"].strip(),
    )
    log_audit(
        actor=request.user,
        module="lost_found",
        action="REPORT_SUBMITTED",
        target_type="LostFoundReport",
        target_id=report.id,
        metadata={"type": report.report_type},
    )
    messages.success(request, f"{report.get_report_type_display()} report submitted for reviewer screening.")
    return redirect("lost_found:index")


@require_POST
@role_required(OperationalRole.LF_REVIEWER)
def review_report_view(request: HttpRequest, report_id: uuid.UUID) -> HttpResponse:
    report = get_object_or_404(LostFoundReport, id=report_id)
    new_status = request.POST["status"]
    if new_status not in {
        LostFoundReport.Status.ACTIVE,
        LostFoundReport.Status.NEEDS_INFO,
        LostFoundReport.Status.REJECTED,
    }:
        messages.error(request, "Invalid review outcome.")
        return redirect("lost_found:index")

    report.status = new_status
    report.reviewer_note = request.POST.get("reviewer_note", "").strip()
    report.save(update_fields=["status", "reviewer_note"])
    log_audit(
        actor=request.user,
        module="lost_found",
        action="REPORT_REVIEWED",
        target_type="LostFoundReport",
        target_id=report.id,
        reason=report.reviewer_note,
        metadata={"new_status": new_status},
    )
    messages.success(request, f"Report marked as {report.get_status_display()}.")
    return redirect("lost_found:index")


@require_POST
@role_required(OperationalRole.LF_REVIEWER)
def suggest_match_view(request: HttpRequest) -> HttpResponse:
    lost_report = get_object_or_404(
        LostFoundReport, id=request.POST["lost_report_id"], report_type=LostFoundReport.ReportType.LOST
    )
    found_report = get_object_or_404(
        LostFoundReport, id=request.POST["found_report_id"], report_type=LostFoundReport.ReportType.FOUND
    )
    rationale = request.POST.get("rationale", "Matching category/location — UNVERIFIED lead only").strip()
    match, _ = PotentialMatch.objects.get_or_create(
        lost_report=lost_report,
        found_report=found_report,
        defaults={"rationale": rationale},
    )
    log_audit(
        actor=request.user,
        module="lost_found",
        action="POTENTIAL_MATCH_RECORDED",
        target_type="PotentialMatch",
        target_id=match.id,
        reason=rationale,
    )
    messages.info(request, "Potential match logged (explicitly unverified — ownership claim still required).")
    return redirect("lost_found:index")


@require_POST
@role_required(OperationalRole.STUDENT)
def submit_claim_view(request: HttpRequest) -> HttpResponse:
    found_report = get_object_or_404(
        LostFoundReport,
        id=request.POST["found_report_id"],
        report_type=LostFoundReport.ReportType.FOUND,
        status=LostFoundReport.Status.ACTIVE,
    )
    claim = OwnershipClaim.objects.create(
        found_report=found_report,
        claimant=request.user,
        evidence_description=request.POST["evidence_description"].strip(),
    )
    log_audit(
        actor=request.user,
        module="lost_found",
        action="OWNERSHIP_CLAIM_SUBMITTED",
        target_type="OwnershipClaim",
        target_id=claim.id,
    )
    messages.success(request, "Ownership claim submitted for reviewer verification.")
    return redirect("lost_found:index")


@require_POST
@role_required(OperationalRole.LF_REVIEWER, OperationalRole.SECURITY_OFFICER)
def decide_claim_view(request: HttpRequest, claim_id: uuid.UUID) -> HttpResponse:
    claim = get_object_or_404(OwnershipClaim, id=claim_id)
    if (
        request.user.role == OperationalRole.SECURITY_OFFICER
        and claim.assigned_security_officer_id != request.user.id
    ):
        raise PermissionDenied("Security Officers may only update assigned cases.")

    decision = request.POST["decision"]
    reason = request.POST.get("reason", "").strip()

    if decision == "verify":
        claim.status = OwnershipClaim.ClaimStatus.VERIFIED
    elif decision == "needs_evidence":
        claim.status = OwnershipClaim.ClaimStatus.NEEDS_EVIDENCE
    elif decision == "reject":
        claim.status = OwnershipClaim.ClaimStatus.REJECTED
    elif decision == "escalate" and request.user.role == OperationalRole.LF_REVIEWER:
        officer = User.objects.filter(role=OperationalRole.SECURITY_OFFICER, is_active=True).first()
        if not officer:
            messages.error(request, "No active Security Officer configured for escalation.")
            return redirect("lost_found:index")
        claim.status = OwnershipClaim.ClaimStatus.ESCALATED
        claim.assigned_security_officer = officer
    else:
        messages.error(request, "Invalid claim decision.")
        return redirect("lost_found:index")

    claim.reviewer = claim.reviewer or request.user
    claim.decision_reason = reason
    claim.save()

    log_audit(
        actor=request.user,
        module="lost_found",
        action=f"CLAIM_{claim.status}",
        target_type="OwnershipClaim",
        target_id=claim.id,
        reason=reason,
    )
    messages.success(request, f"Claim updated to {claim.get_status_display()}.")
    return redirect("lost_found:index")


@require_POST
@role_required(OperationalRole.LF_REVIEWER, OperationalRole.SECURITY_OFFICER)
def record_handover_view(request: HttpRequest, claim_id: uuid.UUID) -> HttpResponse:
    with transaction.atomic():
        claim = get_object_or_404(OwnershipClaim.objects.select_for_update(), id=claim_id)
        if claim.status != OwnershipClaim.ClaimStatus.VERIFIED:
            messages.error(request, "Cannot record handover: ownership claim must be VERIFIED first (BR-LF-03).")
            return redirect("lost_found:index")

        if hasattr(claim, "handover_record"):
            messages.warning(request, "Handover has already been recorded for this claim.")
            return redirect("lost_found:index")

        note = request.POST.get("verification_note", "").strip() or "Verified student ID at service desk"
        handover = ItemHandover.objects.create(
            claim=claim,
            authorized_staff=request.user,
            recipient_verification_note=note,
        )
        claim.status = OwnershipClaim.ClaimStatus.HANDED_OVER
        claim.save(update_fields=["status"])

        report = claim.found_report
        report.status = LostFoundReport.Status.CLOSED_RETURNED
        report.save(update_fields=["status"])

        log_audit(
            actor=request.user,
            module="lost_found",
            action="ITEM_HANDOVER_RECORDED_AND_CLOSED",
            target_type="ItemHandover",
            target_id=handover.id,
            reason=note,
        )
    messages.success(request, "Authorized handover recorded and case closed as returned.")
    return redirect("lost_found:index")