from django.contrib import admin
from django.core.cache import cache

from .models import (
    AuditLog,
    Candidate,
    Election,
    Notification,
    Participation,
    VoterProfile,
    Vote,
)
from .services import record_admin_action
from .tasks import deliver_notification


def _client_ip(request):
    return request.META.get("REMOTE_ADDR")


def _role(user):
    profile = getattr(user, "voter_profile", None)
    return profile.role if profile else None


@admin.register(Election)
class ElectionAdmin(admin.ModelAdmin):
    list_display = (
        "title",
        "start_date",
        "end_date",
        "is_active",
        "is_published",
        "results_published_at",
    )
    list_filter = ("is_active", "is_published", "start_date")
    search_fields = ("title", "description")
    filter_horizontal = ("managers",)
    readonly_fields = ("results_published_at",)

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser or _role(request.user) == VoterProfile.Role.ADMIN:
            return queryset
        if _role(request.user) == VoterProfile.Role.MANAGER:
            return queryset.filter(managers=request.user).distinct()
        return queryset.none()

    def has_module_permission(self, request):
        return request.user.is_superuser or _role(request.user) in (
            VoterProfile.Role.ADMIN,
            VoterProfile.Role.MANAGER,
        )

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request) and (
            obj is None
            or request.user.is_superuser
            or _role(request.user) == VoterProfile.Role.ADMIN
            or obj.managers.filter(pk=request.user.pk).exists()
        )

    def has_add_permission(self, request):
        return request.user.is_superuser or _role(request.user) == VoterProfile.Role.ADMIN

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser or _role(request.user) == VoterProfile.Role.ADMIN

    def get_fields(self, request, obj=None):
        fields = super().get_fields(request, obj)
        if _role(request.user) == VoterProfile.Role.MANAGER:
            return tuple(field for field in fields if field != "managers")
        return fields

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        cache.delete(f"election-results:{obj.pk}")
        record_admin_action(
            user=request.user,
            action=f"{'Updated' if change else 'Created'} election {obj.title}",
            obj=obj,
            ip_address=_client_ip(request),
        )

    def delete_model(self, request, obj):
        election_id = obj.pk
        record_admin_action(
            user=request.user,
            action=f"Deleted election {obj.title}",
            obj=obj,
            ip_address=_client_ip(request),
        )
        super().delete_model(request, obj)
        cache.delete(f"election-results:{election_id}")

    def delete_queryset(self, request, queryset):
        election_ids = set(queryset.values_list("pk", flat=True))
        super().delete_queryset(request, queryset)
        cache.delete_many(f"election-results:{election_id}" for election_id in election_ids)


@admin.register(Candidate)
class CandidateAdmin(admin.ModelAdmin):
    list_display = ("name", "party", "election")
    list_filter = ("election",)
    search_fields = ("name", "party", "manifesto", "election__title")

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        if request.user.is_superuser or _role(request.user) == VoterProfile.Role.ADMIN:
            return queryset
        if _role(request.user) == VoterProfile.Role.MANAGER:
            return queryset.filter(election__managers=request.user).distinct()
        return queryset.none()

    def has_module_permission(self, request):
        return request.user.is_superuser or _role(request.user) in (
            VoterProfile.Role.ADMIN,
            VoterProfile.Role.MANAGER,
        )

    def has_view_permission(self, request, obj=None):
        return self.has_module_permission(request) and (
            obj is None
            or request.user.is_superuser
            or _role(request.user) == VoterProfile.Role.ADMIN
            or obj.election.managers.filter(pk=request.user.pk).exists()
        )

    def has_add_permission(self, request):
        return request.user.is_superuser or _role(request.user) in (
            VoterProfile.Role.ADMIN,
            VoterProfile.Role.MANAGER,
        )

    def has_change_permission(self, request, obj=None):
        return self.has_view_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return self.has_change_permission(request, obj)

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if (
            db_field.name == "election"
            and _role(request.user) == VoterProfile.Role.MANAGER
        ):
            kwargs["queryset"] = Election.objects.filter(managers=request.user)
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        cache.delete(f"election-results:{obj.election_id}")
        record_admin_action(
            user=request.user,
            action=f"{'Updated' if change else 'Added'} candidate {obj.name}",
            obj=obj,
            ip_address=_client_ip(request),
        )

    def delete_model(self, request, obj):
        election_id = obj.election_id
        super().delete_model(request, obj)
        cache.delete(f"election-results:{election_id}")

    def delete_queryset(self, request, queryset):
        election_ids = set(queryset.values_list("election_id", flat=True))
        super().delete_queryset(request, queryset)
        cache.delete_many(f"election-results:{election_id}" for election_id in election_ids)


@admin.action(description="Approve selected voter accounts")
def approve_voters(modeladmin, request, queryset):
    updated = queryset.update(approval_status=VoterProfile.ApprovalStatus.APPROVED)
    record_admin_action(
        user=request.user,
        action=f"Approved {updated} voter account(s)",
        ip_address=_client_ip(request),
    )
    modeladmin.message_user(request, f"{updated} voter account(s) approved.")


@admin.action(description="Suspend selected voter accounts")
def suspend_voters(modeladmin, request, queryset):
    updated = queryset.update(approval_status=VoterProfile.ApprovalStatus.SUSPENDED)
    record_admin_action(
        user=request.user,
        action=f"Suspended {updated} voter account(s)",
        ip_address=_client_ip(request),
    )
    modeladmin.message_user(request, f"{updated} voter account(s) suspended.")


@admin.register(VoterProfile)
class VoterProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "approval_status", "email_verified", "created_at")
    list_filter = ("role", "approval_status", "email_verified")
    search_fields = ("user__username", "user__email")
    actions = (approve_voters, suspend_voters)
    readonly_fields = ("created_at",)

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        record_admin_action(
            user=request.user,
            action=f"{'Updated' if change else 'Created'} voter profile for {obj.user.username}",
            obj=obj,
            ip_address=_client_ip(request),
        )


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("title", "recipient", "created_at", "read_at")
    list_filter = ("created_at",)
    search_fields = ("title", "message", "recipient__username")
    readonly_fields = ("created_at", "read_at")

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not change:
            deliver_notification.delay(obj.pk)
            record_admin_action(
                user=request.user,
                action=f"Sent notification: {obj.title}",
                obj=obj,
                ip_address=_client_ip(request),
            )


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("timestamp", "user", "action", "object_type", "object_id", "ip_address")
    list_filter = ("timestamp", "object_type")
    search_fields = ("action", "user__username", "object_type", "object_id")
    readonly_fields = tuple(field.name for field in AuditLog._meta.fields)
    date_hierarchy = "timestamp"

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Participation)
class ParticipationAdmin(admin.ModelAdmin):
    list_display = ("user", "election", "voted_at")
    list_filter = ("election", "voted_at")
    search_fields = ("user__username", "election__title")
    readonly_fields = ("user", "election", "voted_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Vote)
class VoteAdmin(admin.ModelAdmin):
    list_display = ("election", "candidate", "voted_at", "receipt")
    list_filter = ("election", "voted_at")
    search_fields = ("candidate__name", "election__title", "receipt")
    readonly_fields = ("election", "candidate", "voted_at", "receipt")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
