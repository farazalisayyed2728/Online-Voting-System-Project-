from rest_framework import serializers

from .models import Candidate, Election


class CandidateSerializer(serializers.ModelSerializer):
    class Meta:
        model = Candidate
        fields = ("id", "name", "party", "manifesto")


class ElectionSerializer(serializers.ModelSerializer):
    status = serializers.SerializerMethodField()
    candidates = CandidateSerializer(many=True, read_only=True, source="candidate_set")

    def get_status(self, election):
        return election.status()

    class Meta:
        model = Election
        fields = (
            "id",
            "title",
            "description",
            "start_date",
            "end_date",
            "status",
            "candidates",
            "results_published_at",
        )


class CastBallotSerializer(serializers.Serializer):
    candidate_id = serializers.IntegerField(min_value=1)
