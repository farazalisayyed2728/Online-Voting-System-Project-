from django.db import models
from django.contrib.auth.models import User
from django.utils import timezone


class Election(models.Model):
    title = models.CharField(max_length=200)
    description = models.TextField()
    start_date = models.DateTimeField(default=timezone.now)
    end_date = models.DateTimeField()
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.title

    def is_open(self):
        now = timezone.now()
        return self.start_date <= now <= self.end_date


class Candidate(models.Model):
    election = models.ForeignKey(Election, on_delete=models.CASCADE)
    name = models.CharField(max_length=100)
    manifesto = models.TextField(blank=True)

    def __str__(self):
        return f"{self.name} ({self.election.title})"

    def get_votes(self):
        return self.vote_set.count()


class Vote(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE)
    candidate = models.ForeignKey(Candidate, on_delete=models.CASCADE)
    election = models.ForeignKey(Election, on_delete=models.CASCADE)
    voted_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'election')

    def __str__(self):
        return f"{self.user.username} voted for {self.candidate.name}"
