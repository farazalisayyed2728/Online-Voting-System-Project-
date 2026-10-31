from datetime import timedelta

from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from .models import (
    AuditLog,
    Candidate,
    Election,
    Participation,
    VoterProfile,
    Vote,
)
from .services import VoteAlreadyCast, VotingNotAllowed, cast_ballot


class VotingWorkflowTests(TestCase):
    def setUp(self):
        now = timezone.now()
        self.user = User.objects.create_user(
            username="voter",
            password="strong-test-password",
            email="voter@example.test",
        )
        self.profile = VoterProfile.objects.create(
            user=self.user,
            approval_status=VoterProfile.ApprovalStatus.APPROVED,
            email_verified=True,
        )
        self.election = Election.objects.create(
            title="Community election",
            description="A test election",
            start_date=now - timedelta(hours=1),
            end_date=now + timedelta(hours=1),
        )
        self.candidate = Candidate.objects.create(
            election=self.election,
            name="Alex Example",
            manifesto="A test manifesto",
        )
        self.other_candidate = Candidate.objects.create(
            election=self.election,
            name="Sam Example",
        )
        self.client.force_login(self.user)

    def test_vote_is_anonymous_and_one_participation_per_election(self):
        ballot = cast_ballot(
            user=self.user, election=self.election, candidate=self.candidate
        )
        self.assertEqual(Participation.objects.get().user, self.user)
        self.assertFalse(any(field.name in ("user", "voter") for field in Vote._meta.fields))
        self.assertEqual(ballot.candidate, self.candidate)
        with self.assertRaises(VoteAlreadyCast):
            cast_ballot(
                user=self.user, election=self.election, candidate=self.other_candidate
            )
        self.assertEqual(Vote.objects.count(), 1)

    def test_unapproved_or_unverified_voter_cannot_vote(self):
        self.profile.approval_status = VoterProfile.ApprovalStatus.PENDING
        self.profile.save(update_fields=("approval_status",))
        with self.assertRaises(VotingNotAllowed):
            cast_ballot(
                user=self.user, election=self.election, candidate=self.candidate
            )
        self.profile.approval_status = VoterProfile.ApprovalStatus.APPROVED
        self.profile.email_verified = False
        self.profile.save(update_fields=("approval_status", "email_verified"))
        with self.assertRaises(VotingNotAllowed):
            cast_ballot(
                user=self.user, election=self.election, candidate=self.candidate
            )
        self.assertEqual(Vote.objects.count(), 0)

    def test_ballot_candidate_must_belong_to_election(self):
        other_election = Election.objects.create(
            title="Other election",
            description="Another election",
            start_date=timezone.now() - timedelta(hours=1),
            end_date=timezone.now() + timedelta(hours=1),
        )
        with self.assertRaises(VotingNotAllowed):
            cast_ballot(user=self.user, election=other_election, candidate=self.candidate)

    def test_voting_requires_post_and_confirmation(self):
        response = self.client.get(
            reverse(
                "candidate_list",
                kwargs={"election_id": self.election.pk},
            )
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("confirm_vote", kwargs={"election_id": self.election.pk}),
            {"candidate_id": self.candidate.pk},
        )
        self.assertEqual(response.status_code, 200)
        response = self.client.post(
            reverse("cast_vote", kwargs={"election_id": self.election.pk}),
            {"candidate_id": self.candidate.pk},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "ANONYMOUS RECEIPT")
        self.assertEqual(Vote.objects.count(), 1)

    def test_unpublished_results_are_not_public(self):
        response = self.client.get(
            reverse("election_results", kwargs={"election_id": self.election.pk})
        )
        self.assertEqual(response.status_code, 404)

    def test_results_are_visible_after_publication(self):
        Vote.objects.create(election=self.election, candidate=self.candidate)
        self.election.end_date = timezone.now() - timedelta(minutes=1)
        self.election.save(update_fields=("end_date",))
        self.election.results_published_at = timezone.now()
        self.election.save(update_fields=("results_published_at",))
        response = self.client.get(
            reverse("election_results", kwargs={"election_id": self.election.pk})
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Alex Example")
        self.assertContains(response, "1")

    def test_voter_dashboard_and_api(self):
        response = self.client.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Welcome back")

        api_client = APIClient()
        response = api_client.get(reverse("api_elections"))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data["count"], 1)
        api_client.force_authenticate(self.user)
        response = api_client.get(reverse("api_dashboard"))
        self.assertEqual(response.status_code, 200)

    def test_api_vote_enforces_eligibility_and_one_vote(self):
        api_client = APIClient()
        api_client.force_authenticate(self.user)
        url = reverse("api_vote", kwargs={"election_id": self.election.pk})
        response = api_client.post(url, {"candidate_id": self.candidate.pk}, format="json")
        self.assertEqual(response.status_code, 201)
        self.assertIn("receipt", response.data)
        response = api_client.post(
            url, {"candidate_id": self.other_candidate.pk}, format="json"
        )
        self.assertEqual(response.status_code, 409)


class AppendOnlyAuditTests(TestCase):
    def test_audit_entries_cannot_be_modified_or_deleted(self):
        record = AuditLog.objects.create(action="Test event")
        with self.assertRaises(ValidationError):
            record.save()
        with self.assertRaises(ValidationError):
            record.delete()


class LoginThrottleTests(TestCase):
    def setUp(self):
        cache.clear()
        User.objects.create_user(username="sign-in-user", password="correct-password")

    def tearDown(self):
        cache.clear()

    def test_five_failed_sign_ins_throttle_further_attempts(self):
        login_url = reverse("login")
        for _ in range(5):
            response = self.client.post(
                login_url,
                {"username": "sign-in-user", "password": "incorrect-password"},
            )
            self.assertEqual(response.status_code, 200)
        response = self.client.post(
            login_url,
            {"username": "sign-in-user", "password": "correct-password"},
        )
        self.assertEqual(response.status_code, 429)
