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
from apps.facilities.models import FacilityTicket, TicketTransition


@role_required(
    OperationalRole.STUDENT,
    OperationalRole.UTILITY_STAFF,
    OperationalRole.IT_STAFF,
    OperationalRole.MANAGEMENT_OFFICER,
    OperationalRole.SYSTEM_ADMIN,
)
def index_view(request: HttpRequest) -> HttpResponse:
    user = request.user
    if user.role == OperationalRole.STUDENT:
        tickets = FacilityTicket.objects.filter(reporter=user).prefetch_related("transitions__actor")
    else:
        tickets = FacilityTicket.objects.select_related("reporter", "assigned_to").prefetch_related(
            "transitions__actor"
        )

    staff_pool = User.objects.filter(
        role__in=[OperationalRole.UTILITY_STAFF, OperationalRole.IT_STAFF], is_active=True
    )

    context = {
        "tickets": tickets,
        "staff_pool": staff_pool,
        "statuses": FacilityTicket.Status.choices,
        "priorities": FacilityTicket.Priority.choices,
    }
    return render(request, "facilities/index.html", context)


@require_POST
@role_required(OperationalRole.STUDENT)
def submit_ticket_view(request: HttpRequest) -> HttpResponse:
    with transaction.atomic():
        ticket = FacilityTicket.objects.create(
            reporter=request.user,
            issue_type=request.POST["issue_type"],
            category=request.POST["category"].strip(),
            location=request.POST["location"].strip(),
            description=request.POST["description"].strip(),
        )
        TicketTransition.objects.create(
            ticket=ticket,
            from_status="NEW",
            to_status=ticket.status,
            actor=request.user,
            note="Ticket submitted by student.",
        )
        log_audit(
            actor=request.user,
            module="facilities",
            action="TICKET_SUBMITTED",
            target_type="FacilityTicket",
            target_id=ticket.id,
        )
    messages.success(request, f"Ticket created (ID: {str(ticket.id)[:8]}).")
    return redirect("facilities:index")


@require_POST
@role_required(
    OperationalRole.STUDENT,
    OperationalRole.UTILITY_STAFF,
    OperationalRole.IT_STAFF,
    OperationalRole.MANAGEMENT_OFFICER,
)
def update_ticket_view(request: HttpRequest, ticket_id: uuid.UUID) -> HttpResponse:
    with transaction.atomic():
        ticket = get_object_or_404(FacilityTicket.objects.select_for_update(), id=ticket_id)
        user = request.user
        new_status = request.POST["status"]
        note = request.POST.get("note", "").strip()

        # Role boundary enforcement (FR-UT-06..12)
        if user.role == OperationalRole.STUDENT:
            if ticket.reporter_id != user.id:
                raise PermissionDenied("You can only interact with your own tickets.")
            if new_status == FacilityTicket.Status.REOPENED and ticket.status == FacilityTicket.Status.RESOLVED:
                if not note:
                    messages.error(request, "Please explain why the resolved issue is being reopened.")
                    return redirect("facilities:index")
                ticket.reopen_count += 1
            elif new_status == FacilityTicket.Status.UNDER_REVIEW and ticket.status == FacilityTicket.Status.NEEDS_INFO:
                pass  # Reporter providing requested clarification
            else:
                raise PermissionDenied("Students cannot assign or resolve facility tickets.")
        else:
            if new_status == FacilityTicket.Status.RESOLVED and not note:
                messages.error(request, "Resolution requires a documented maintenance note.")
                return redirect("facilities:index")
            assignee_id = request.POST.get("assigned_to_id")
            if assignee_id:
                ticket.assigned_to = get_object_or_404(User, id=assignee_id)
            priority = request.POST.get("priority")
            if priority in {p[0] for p in FacilityTicket.Priority.choices}:
                ticket.priority = priority
            if new_status == FacilityTicket.Status.RESOLVED:
                ticket.resolution_notes = note

        old_status = ticket.status
        ticket.status = new_status
        ticket.save()

        TicketTransition.objects.create(
            ticket=ticket,
            from_status=old_status,
            to_status=new_status,
            actor=user,
            note=note or f"Status updated to {new_status}",
        )
        log_audit(
            actor=user,
            module="facilities",
            action="TICKET_STATUS_CHANGED",
            target_type="FacilityTicket",
            target_id=ticket.id,
            reason=note,
            metadata={"from": old_status, "to": new_status},
        )
    messages.success(request, f"Ticket updated: {old_status} -> {new_status}.")
    return redirect("facilities:index")