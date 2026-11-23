from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from apps.accounts.models import AuditEvent, User


@admin.register(User)
class CustomUserAdmin(UserAdmin):
    list_display = ("username", "institutional_id", "role", "is_active")
    list_filter = ("role", "is_active")
    fieldsets = UserAdmin.fieldsets + (
        ("CampusHub Identity", {"fields": ("institutional_id", "role")}),
    )


@admin.register(AuditEvent)
class AuditEventAdmin(admin.ModelAdmin):
    list_display = ("created_at", "actor", "module", "action", "target_type", "target_id")
    list_filter = ("module", "action")
    readonly_fields = ("actor", "module", "action", "target_type", "target_id", "reason", "metadata", "created_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False