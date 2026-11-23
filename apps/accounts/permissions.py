from __future__ import annotations

from functools import wraps
from typing import Callable
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse


def role_required(*allowed_roles: str) -> Callable:
    """Server-side deny-by-default RBAC decorator (FR-AUTH-02, NFR-SEC-01)."""

    allowed = set(allowed_roles)

    def decorator(view_func: Callable[..., HttpResponse]) -> Callable[..., HttpResponse]:
        @login_required
        @wraps(view_func)
        def _wrapped(request: HttpRequest, *args, **kwargs) -> HttpResponse:
            user = request.user
            if not user.is_active or getattr(user, "role", None) not in allowed:
                raise PermissionDenied("Access denied for your operational role.")
            return view_func(request, *args, **kwargs)

        return _wrapped

    return decorator