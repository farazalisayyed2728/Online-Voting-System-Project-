import hashlib

from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.core.cache import cache
from django.core.paginator import Paginator
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone

from .forms import UserRegisterForm
from .models import (
    AuditLog,
    Candidate,
    Election,
    EmailVerificationToken,
    Notification,
    Participation,
    VoterProfile,
    Vote,
)
from .services import (
    VoteAlreadyCast,
    VotingNotAllowed,
    cast_ballot,
    election_results,
    publish_results,
)
from .tasks import send_email_verification


class CustomLoginView(LoginView):
    template_name = "voting/login.html"
    max_failed_attempts = 5
    throttle_window = 60

    def _attempts_key(self):
        remote_addr = self.request.META.get("REMOTE_ADDR", "unknown")
        address_hash = hashlib.sha256(remote_addr.encode("utf-8")).hexdigest()
        return f"login-failures:{address_hash}"

    def dispatch(self, request, *args, **kwargs):
        if (
            request.method == "POST"
            and cache.get(self._attempts_key(), 0) >= self.max_failed_attempts
        ):
            form = self.get_form()
            form.add_error(None, "Too many failed sign-in attempts. Try again in one minute.")
            return self.render_to_response(
                self.get_context_data(form=form), status=429
            )
        return super().dispatch(request, *args, **kwargs)

    def form_invalid(self, form):
        key = self._attempts_key()
        attempts = cache.get(key, 0) + 1
        cache.set(key, attempts, timeout=self.throttle_window)
        if attempts >= self.max_failed_attempts:
            form.add_error(
                None, "Too many failed sign-in attempts. Try again in one minute."
            )
        return super().form_invalid(form)

    def form_valid(self, form):
        cache.delete(self._attempts_key())
        return super().form_valid(form)


def register(request):
    if request.method == "POST":
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            user = form.save()
            VoterProfile.objects.create(user=user)
            token = EmailVerificationToken.objects.create(user=user)
            verification_url = request.build_absolute_uri(
                reverse("verify_email", args=(token.token,))
            )
            send_email_verification.delay(user.pk, verification_url)
            messages.success(
                request,
                "Account created. Verify your email before voting; an administrator must also approve your voter account.",
            )
            return redirect("login")
    else:
        form = UserRegisterForm()
    return render(request, "voting/register.html", {"form": form})


def verify_email(request, token):
    verification = get_object_or_404(EmailVerificationToken, token=token)
    if not verification.is_valid():
        messages.error(request, "This verification link is invalid or has expired.")
        return redirect("login")
    profile, _ = VoterProfile.objects.get_or_create(user=verification.user)
    profile.email_verified = True
    profile.save(update_fields=("email_verified",))
    verification.used_at = timezone.now()
    verification.save(update_fields=("used_at",))
    messages.success(request, "Your email has been verified.")
    return redirect("login")


def logout_view(request):
    logout(request)
    return redirect("login")


@login_required
def home(request):
    profile, _ = VoterProfile.objects.get_or_create(user=request.user)
    now = timezone.now()
    elections = Election.objects.filter(is_published=True, is_active=True)
    voted_ids = Participation.objects.filter(user=request.user).values_list(
        "election_id", flat=True
    )
    active_elections = elections.filter(
        start_date__lte=now, end_date__gte=now
    ).exclude(pk__in=voted_ids)
    return render(
        request,
        "voting/home.html",
        {
            "profile": profile,
            "active_elections": active_elections,
            "upcoming_elections": elections.filter(start_date__gt=now),
            "voted_elections": Election.objects.filter(pk__in=voted_ids).order_by(
                "-start_date"
            ),
            "completed_elections": elections.filter(end_date__lt=now),
            "notifications": Notification.objects.filter(
                Q(recipient__isnull=True) | Q(recipient=request.user)
            )[:5],
            "participation_count": Participation.objects.filter(user=request.user).count(),
        },
    )


def election_list(request):
    elections = Election.objects.filter(is_published=True).annotate(
        vote_count=Count("ballots")
    )
    query = request.GET.get("q", "").strip()
    if query:
        elections = elections.filter(title__icontains=query) | elections.filter(
            description__icontains=query
        )
    status_filter = request.GET.get("status", "")
    now = timezone.now()
    if status_filter == "active":
        elections = elections.filter(
            is_active=True, start_date__lte=now, end_date__gte=now
        )
    elif status_filter == "upcoming":
        elections = elections.filter(is_active=True, start_date__gt=now)
    elif status_filter == "completed":
        elections = elections.filter(is_active=True, end_date__lt=now)
    paginator = Paginator(elections.order_by("-start_date").distinct(), 9)
    page = paginator.get_page(request.GET.get("page"))
    return render(
        request,
        "voting/election_list.html",
        {"elections": page, "query": query, "status_filter": status_filter},
    )


@login_required
def candidate_list(request, election_id):
    election = get_object_or_404(Election, pk=election_id, is_published=True)
    candidates = Candidate.objects.filter(election=election)
    has_voted = Participation.objects.filter(user=request.user, election=election).exists()
    return render(
        request,
        "voting/candidate_list.html",
        {
            "election": election,
            "candidates": candidates,
            "has_voted": has_voted,
            "is_open": election.is_open(),
        },
    )


@login_required
def confirm_vote(request, election_id):
    if request.method != "POST":
        return redirect("candidate_list", election_id=election_id)
    election = get_object_or_404(Election, pk=election_id, is_published=True)
    candidate = get_object_or_404(
        Candidate, pk=request.POST.get("candidate_id"), election=election
    )
    if not election.is_open():
        messages.error(request, "Voting is currently closed for this election.")
        return redirect("candidate_list", election_id=election_id)
    if Participation.objects.filter(user=request.user, election=election).exists():
        messages.warning(request, "You have already voted in this election.")
        return redirect("candidate_list", election_id=election_id)
    profile, _ = VoterProfile.objects.get_or_create(user=request.user)
    return render(
        request,
        "voting/confirm_vote.html",
        {"election": election, "candidate": candidate, "profile": profile},
    )


@login_required
def cast_vote(request, election_id):
    if request.method != "POST":
        return redirect("candidate_list", election_id=election_id)
    election = get_object_or_404(Election, pk=election_id, is_published=True)
    candidate = get_object_or_404(
        Candidate, pk=request.POST.get("candidate_id"), election=election
    )
    try:
        ballot = cast_ballot(user=request.user, election=election, candidate=candidate)
    except VoteAlreadyCast:
        messages.warning(request, "You have already voted in this election.")
        return redirect("candidate_list", election_id=election_id)
    except VotingNotAllowed as error:
        messages.error(request, str(error))
        return redirect("candidate_list", election_id=election_id)
    return render(
        request,
        "voting/vote_receipt.html",
        {"election": election, "receipt": ballot.receipt},
    )


def election_results_view(request, election_id):
    election = get_object_or_404(Election, pk=election_id, is_published=True)
    can_view_unpublished = request.user.is_authenticated and (
        request.user.is_staff or election.managers.filter(pk=request.user.pk).exists()
    )
    if election.results_published_at is None and not can_view_unpublished:
        raise Http404("Results have not been published.")
    result_data = election_results(election)
    winner = max(result_data["results"], key=lambda row: row["vote_count"], default=None)
    return render(
        request,
        "voting/result.html",
        {
            "election": election,
            "results": result_data["results"],
            "total_votes": result_data["total_votes"],
            "result_data": result_data,
            "winner": winner if winner and winner["vote_count"] else None,
            "chart_labels": [item["name"] for item in result_data["results"]],
            "chart_votes": [item["vote_count"] for item in result_data["results"]],
        },
    )


def _client_ip(request):
    return request.META.get("REMOTE_ADDR")


@login_required
def publish_election_results(request, election_id):
    if request.method != "POST":
        return redirect("election_results", election_id=election_id)
    election = get_object_or_404(Election, pk=election_id)
    if not (
        request.user.is_staff or election.managers.filter(pk=request.user.pk).exists()
    ):
        raise Http404
    try:
        publish_results(election=election, user=request.user, ip_address=_client_ip(request))
    except VotingNotAllowed as error:
        messages.error(request, str(error))
    else:
        messages.success(request, "Election results are now published.")
    return redirect("election_results", election_id=election_id)


@login_required
def admin_dashboard(request):
    profile, _ = VoterProfile.objects.get_or_create(user=request.user)
    if not request.user.is_staff and profile.role not in (
        VoterProfile.Role.ADMIN,
        VoterProfile.Role.MANAGER,
    ):
        raise Http404

    elections = Election.objects.all()
    if not request.user.is_staff and profile.role == VoterProfile.Role.MANAGER:
        elections = elections.filter(managers=request.user)
    now = timezone.now()
    active = elections.filter(
        is_published=True, is_active=True, start_date__lte=now, end_date__gte=now
    )
    total_voters = VoterProfile.objects.filter(
        role=VoterProfile.Role.VOTER,
        approval_status=VoterProfile.ApprovalStatus.APPROVED,
    ).count()
    votes = Vote.objects.filter(election__in=elections)
    vote_count = votes.count()
    participation_count = Participation.objects.filter(election__in=elections).count()
    election_count = elections.filter(is_published=True).count()
    candidates = Candidate.objects.filter(election__in=elections).count()
    completed = elections.filter(is_published=True, end_date__lt=now).count()
    pending_voters = VoterProfile.objects.filter(
        approval_status=VoterProfile.ApprovalStatus.PENDING
    ).count()
    recent_audit = AuditLog.objects.select_related("user")[:8]
    return render(
        request,
        "voting/admin_dashboard.html",
        {
            "elections": elections.order_by("-start_date")[:8],
            "active_count": active.count(),
            "total_voters": total_voters,
            "candidate_count": candidates,
            "completed_count": completed,
            "vote_count": vote_count,
            "participation": round(
                participation_count * 100 / (total_voters * election_count), 1
            )
            if total_voters and election_count
            else 0,
            "pending_voters": pending_voters,
            "recent_audit": recent_audit,
            "can_manage_users": request.user.is_staff,
        },
    )


@login_required
def notification_list(request):
    notifications = Notification.objects.filter(
        recipient__isnull=True
    ) | Notification.objects.filter(recipient=request.user)
    return render(
        request, "voting/notifications.html", {"notifications": notifications.distinct()}
    )
