from django.db.models import Count, Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework import generics, permissions, status
from rest_framework.exceptions import PermissionDenied
from rest_framework.filters import OrderingFilter, SearchFilter
from rest_framework.pagination import PageNumberPagination
from rest_framework.response import Response
from rest_framework.throttling import AnonRateThrottle, UserRateThrottle
from rest_framework.views import APIView

from .models import Candidate, Election, Participation, VoterProfile
from .serializers import (
    CastBallotSerializer,
    CandidateSerializer,
    ElectionSerializer,
)
from .services import VoteAlreadyCast, VotingNotAllowed, cast_ballot, election_results


class VoteRateThrottle(UserRateThrottle):
    scope = "vote"


class ElectionPagination(PageNumberPagination):
    page_size = 10
    page_size_query_param = "page_size"
    max_page_size = 50


class ElectionListAPI(generics.ListAPIView):
    permission_classes = (permissions.AllowAny,)
    serializer_class = ElectionSerializer
    pagination_class = ElectionPagination
    filter_backends = (SearchFilter, OrderingFilter)
    search_fields = ("title", "description", "candidate__name")
    ordering_fields = ("title", "start_date", "end_date")
    ordering = ("-start_date",)

    def get_queryset(self):
        queryset = Election.objects.filter(is_published=True).prefetch_related("candidate_set")
        status_filter = self.request.query_params.get("status")
        now = timezone.now()
        if status_filter == "active":
            queryset = queryset.filter(is_active=True, start_date__lte=now, end_date__gte=now)
        elif status_filter == "upcoming":
            queryset = queryset.filter(is_active=True, start_date__gt=now)
        elif status_filter == "completed":
            queryset = queryset.filter(is_active=True, end_date__lt=now)
        return queryset.distinct()


class CandidateListAPI(generics.ListAPIView):
    serializer_class = CandidateSerializer
    permission_classes = (permissions.AllowAny,)
    pagination_class = ElectionPagination
    filter_backends = (SearchFilter, OrderingFilter)
    search_fields = ("name", "party", "manifesto")
    ordering_fields = ("name",)
    ordering = ("name",)

    def get_queryset(self):
        election = get_object_or_404(Election, pk=self.kwargs["election_id"])
        if not election.is_published:
            raise PermissionDenied("This election is not published.")
        return Candidate.objects.filter(election=election)


class CastBallotAPI(APIView):
    permission_classes = (permissions.IsAuthenticated,)
    throttle_classes = (VoteRateThrottle,)

    def post(self, request, election_id):
        serializer = CastBallotSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        election = get_object_or_404(Election, pk=election_id)
        candidate = get_object_or_404(
            Candidate, pk=serializer.validated_data["candidate_id"], election=election
        )
        try:
            ballot = cast_ballot(user=request.user, election=election, candidate=candidate)
        except VoteAlreadyCast:
            return Response(
                {"detail": "You have already voted in this election."},
                status=status.HTTP_409_CONFLICT,
            )
        except VotingNotAllowed as error:
            return Response({"detail": str(error)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(
            {"receipt": str(ballot.receipt), "message": "Your ballot has been recorded."},
            status=status.HTTP_201_CREATED,
        )


class ElectionResultsAPI(APIView):
    permission_classes = (permissions.AllowAny,)
    throttle_classes = (AnonRateThrottle, UserRateThrottle)

    def get(self, request, election_id):
        election = get_object_or_404(Election, pk=election_id)
        is_manager = (
            request.user.is_authenticated
            and (
                request.user.is_staff
                or election.managers.filter(pk=request.user.pk).exists()
            )
        )
        if election.results_published_at is None and not is_manager:
            return Response(
                {"detail": "Results have not been published."},
                status=status.HTTP_403_FORBIDDEN,
            )
        return Response(election_results(election))


class DashboardAPI(APIView):
    permission_classes = (permissions.IsAuthenticated,)

    def get(self, request):
        now = timezone.now()
        participations = Participation.objects.filter(user=request.user)
        voted_ids = participations.values_list("election_id", flat=True)
        elections = Election.objects.filter(is_published=True, is_active=True)
        profile, _ = VoterProfile.objects.get_or_create(user=request.user)
        return Response(
            {
                "username": request.user.get_username(),
                "role": profile.role,
                "approval_status": profile.approval_status,
                "active_elections": ElectionSerializer(
                    elections.filter(
                        start_date__lte=now, end_date__gte=now
                    ).exclude(pk__in=voted_ids),
                    many=True,
                ).data,
                "upcoming_elections": ElectionSerializer(
                    elections.filter(start_date__gt=now), many=True
                ).data,
                "participation_count": participations.count(),
                "completed_elections": elections.filter(end_date__lt=now).count(),
            }
        )


class AdminAnalyticsAPI(APIView):
    permission_classes = (permissions.IsAdminUser,)

    def get(self, request):
        now = timezone.now()
        voter_count = VoterProfile.objects.filter(
            role=VoterProfile.Role.VOTER,
            approval_status=VoterProfile.ApprovalStatus.APPROVED,
        ).count()
        totals = Election.objects.aggregate(
            election_count=Count("id", distinct=True),
            candidate_count=Count("candidate", distinct=True),
            active_count=Count(
                "id",
                filter=Q(
                    is_published=True,
                    is_active=True,
                    start_date__lte=now,
                    end_date__gte=now,
                ),
                distinct=True,
            ),
        )
        vote_count = Election.objects.aggregate(total=Count("ballots"))["total"] or 0
        participation_count = Participation.objects.filter(
            election__is_published=True
        ).values("user_id", "election_id").distinct().count()
        published_elections = Election.objects.filter(is_published=True).count()
        return Response(
            {
                "registered_voters": voter_count,
                "candidates": totals["candidate_count"],
                "elections": totals["election_count"],
                "active_elections": totals["active_count"],
                "votes_cast": vote_count,
                "participation_percentage": (
                    round(
                        participation_count * 100 / (voter_count * published_elections),
                        2,
                    )
                    if voter_count and published_elections
                    else 0
                ),
            }
        )
