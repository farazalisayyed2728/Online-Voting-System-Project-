import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


class VoterProfile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        MANAGER = "manager", "Election manager"
        VOTER = "voter", "Voter"

    class ApprovalStatus(models.TextChoices):
        PENDING = "pending", "Pending"
        APPROVED = "approved", "Approved"
        SUSPENDED = "suspended", "Suspended"

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="voter_profile"
    )
    role = models.CharField(max_length=12, choices=Role.choices, default=Role.VOTER)
    approval_status = models.CharField(
        max_length=12,
        choices=ApprovalStatus.choices,
        default=ApprovalStatus.PENDING,
    )
    email_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.user.username} ({self.get_role_display()})"


class EmailVerificationToken(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="verification_tokens"
    )
    token = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)
    used_at = models.DateTimeField(null=True, blank=True)

    def is_valid(self):
        return (
            self.used_at is None
            and self.created_at >= timezone.now() - timedelta(hours=24)
        )


class Election(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)
    is_published = models.BooleanField(default=True)
    results_published_at = models.DateTimeField(null=True, blank=True)
    managers = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="managed_elections"
    )

    class Meta:
        ordering = ("-start_date",)
        constraints = [
            models.CheckConstraint(
                condition=models.Q(end_date__gt=models.F("start_date")),
                name="election_end_after_start",
            )
        ]

    def __str__(self):
        return self.title

    def status(self):
        if not self.is_published:
            return "draft"
        if not self.is_active:
            return "closed"
        now = timezone.now()
        if now < self.start_date:
            return "upcoming"
        if now <= self.end_date:
            return "active"
        return "completed"

    def is_open(self):
        now = timezone.now()
        return self.is_published and self.is_active and self.start_date <= now <= self.end_date


class Candidate(models.Model):
    election = models.ForeignKey(Election, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    party = models.CharField(max_length=100, blank=True)
    manifesto = models.TextField(blank=True)

    class Meta:
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=("election", "name"), name="unique_candidate_per_election")
        ]

    def __str__(self):
        return f"{self.name} ({self.election.title})"

    def get_votes(self):
        return self.ballots.count()


class Participation(models.Model):
    """Records eligibility use without linking a voter to their anonymous ballot."""

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="participation_records"
    )
    election = models.ForeignKey(
        Election, on_delete=models.PROTECT, related_name="participation_records"
    )
    voted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=("user", "election"), name="one_participation_per_voter_election"
            )
        ]
        ordering = ("-voted_at",)

    def __str__(self):
        return f"Participation in {self.election.title}"


class Vote(models.Model):
    """An anonymous ballot; voter identity is stored only in Participation."""

    candidate = models.ForeignKey(
        Candidate, on_delete=models.PROTECT, related_name="ballots"
    )
    election = models.ForeignKey(Election, on_delete=models.PROTECT, related_name="ballots")
    receipt = models.UUIDField(default=uuid.uuid4, unique=True, editable=False)
    voted_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ("voted_at",)

    def clean(self):
        if self.candidate_id and self.election_id:
            if self.candidate.election_id != self.election_id:
                raise ValidationError("The selected candidate does not belong to this election.")

    def __str__(self):
        return f"Anonymous ballot for {self.election.title}"


class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="election_notifications",
    )
    title = models.CharField(max_length=160)
    message = models.TextField()
    created_at = models.DateTimeField(auto_now_add=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ("-created_at",)

    def __str__(self):
        return self.title


class AuditLog(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    action = models.CharField(max_length=255)
    object_type = models.CharField(max_length=100, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    timestamp = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ("-timestamp",)

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValidationError("Audit records are append-only.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Audit records are append-only.")

    def __str__(self):
        return self.action
