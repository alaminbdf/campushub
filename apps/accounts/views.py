from __future__ import annotations

from django.contrib import messages
from django.contrib.auth import authenticate, login, logout
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.models import AuditEvent, OperationalRole, User, log_audit
from apps.accounts.permissions import role_required


def login_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("dashboards:home")

    if request.method == "POST":
        username = request.POST.get("username", "").strip()
        password = request.POST.get("password", "")
        user = authenticate(request, username=username, password=password)
        if user is not None and user.is_active:
            login(request, user)
            log_audit(
                actor=user,
                module="accounts",
                action="USER_SIGNED_IN",
                target_type="User",
                target_id=user.id,
            )
            return redirect("dashboards:home")
        messages.error(request, "Invalid credentials or account disabled.")

    return render(request, "accounts/login.html")


@require_POST
def logout_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        log_audit(
            actor=request.user,
            module="accounts",
            action="USER_SIGNED_OUT",
            target_type="User",
            target_id=request.user.id,
        )
        logout(request)
    return redirect("accounts:login")


@role_required(OperationalRole.SYSTEM_ADMIN)
def admin_users_view(request: HttpRequest) -> HttpResponse:
    if request.method == "POST":
        target = get_object_or_404(User, id=request.POST.get("user_id"))
        new_role = request.POST.get("role", target.role)
        new_active = request.POST.get("is_active") == "on"

        valid_roles = {choice[0] for choice in OperationalRole.choices}
        if new_role not in valid_roles:
            messages.error(request, "Invalid operational role selected.")
            return redirect("accounts:admin_users")

        # ADM-01 Alt Flow 1.d: prevent disabling or demoting the last active System Administrator
        is_leaving_admin = target.role == OperationalRole.SYSTEM_ADMIN and (
            not new_active or new_role != OperationalRole.SYSTEM_ADMIN
        )
        active_admins = User.objects.filter(role=OperationalRole.SYSTEM_ADMIN, is_active=True).count()
        if is_leaving_admin and active_admins <= 1:
            messages.error(request, "Blocked: cannot disable or demote the last active System Administrator.")
            return redirect("accounts:admin_users")

        old_state = {"role": target.role, "is_active": target.is_active}
        target.role = new_role
        target.is_active = new_active
        target.save(update_fields=["role", "is_active"])

        log_audit(
            actor=request.user,
            module="accounts",
            action="ACCOUNT_ROLE_UPDATED",
            target_type="User",
            target_id=target.id,
            reason=request.POST.get("reason", "Administrative update"),
            metadata={"before": old_state, "after": {"role": target.role, "is_active": target.is_active}},
        )
        messages.success(request, f"Updated {target.institutional_id} successfully.")
        return redirect("accounts:admin_users")

    context = {
        "users": User.objects.all().order_by("role", "institutional_id"),
        "roles": OperationalRole.choices,
        "audit_events": AuditEvent.objects.select_related("actor")[:30],
    }
    return render(request, "accounts/admin_users.html", context)