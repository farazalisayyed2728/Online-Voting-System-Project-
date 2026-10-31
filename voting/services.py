from django.core.cache import cache
from django.db import IntegrityError, transaction
from django.db.models import Count
from django.utils import timezone

from .models import AuditLog, Candidate, Election, Participation, Vote
from .tasks import send_ballot_receipt


class VoteAlreadyCast(Exception):
    pass


class VotingNotAllowed(Exception):
    pass


def cast_ballot(*, user, election, candidate):
    if not election.is_open():
        raise VotingNotAllowed("Voting is currently closed for this election.")
    if candidate.election_id != election.id:
        raise VotingNotAllowed("The selected candidate does not belong to this election.")

    profile = getattr(user, "voter_profile", None)
    if (
        profile is None
        or profile.approval_status != "approved"
        or not profile.email_verified
    ):
        raise VotingNotAllowed("Your voter account must be approved and email-verified to vote.")

    try:
        with transaction.atomic():
            try:
                with transaction.atomic():
                    Participation.objects.create(user=user, election=election)
            except IntegrityError as error:
                raise VoteAlreadyCast from error

            ballot = Vote.objects.create(election=election, candidate=candidate)
            transaction.on_commit(lambda: cache.delete(f"election-results:{election.pk}"))
            transaction.on_commit(
                lambda: send_ballot_receipt.delay(
                    user.email, election.title, str(ballot.receipt)
                )
            )
            return ballot
    except IntegrityError:
        raise


def election_results(election):
    cache_key = f"election-results:{election.pk}"
    cached = cache.get(cache_key)
    if cached is not None:
        return cached

    candidates = Candidate.objects.filter(election=election).annotate(
        vote_count=Count("ballots", distinct=True)
    )
    total_votes = Vote.objects.filter(election=election).count()
    rows = [
        {
            "id": candidate.pk,
            "name": candidate.name,
            "party": candidate.party,
            "vote_count": candidate.vote_count,
            "percentage": (
                round(candidate.vote_count * 100 / total_votes, 2) if total_votes else 0
            ),
        }
        for candidate in candidates
    ]
    results = {
        "total_votes": total_votes,
        "participation_count": Participation.objects.filter(election=election).count(),
        "results": rows,
        "published_at": election.results_published_at,
    }
    cache.set(cache_key, results, timeout=60)
    return results


def record_admin_action(*, user, action, obj=None, ip_address=None):
    AuditLog.objects.create(
        user=user if user.is_authenticated else None,
        action=action,
        object_type=obj.__class__.__name__ if obj else "",
        object_id=str(obj.pk) if obj and obj.pk else "",
        ip_address=ip_address,
    )


def publish_results(*, election, user, ip_address=None):
    if timezone.now() <= election.end_date:
        raise VotingNotAllowed("Results can only be published after voting closes.")
    election.results_published_at = timezone.now()
    election.save(update_fields=("results_published_at",))
    cache.delete(f"election-results:{election.pk}")
    record_admin_action(
        user=user,
        action=f"Published results for {election.title}",
        obj=election,
        ip_address=ip_address,
    )
