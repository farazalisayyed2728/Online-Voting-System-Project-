from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView
from django.contrib import messages
from django.utils import timezone
from django.db.models import Count
from django.contrib.auth import logout

from .models import Election, Candidate, Vote
from .forms import UserRegisterForm


#  AUTHENTICATION VIEWS


class CustomLoginView(LoginView):
    template_name = 'voting/login.html'


def register(request):
    """User Registration View"""
    if request.method == 'POST':
        form = UserRegisterForm(request.POST)
        if form.is_valid():
            form.save()
            username = form.cleaned_data.get('username')
            messages.success(request, f'Account created for {username}! You can now log in.')
            return redirect('login')
    else:
        form = UserRegisterForm()
    return render(request, 'voting/register.html', {'form': form})


def logout_view(request):
    """Logout the user and redirect to login"""
    logout(request)
    return redirect('login')



# DASHBOARD / HOME


@login_required
def home(request):
    open_elections = Election.objects.filter(
        is_active=True,
        start_date__lte=timezone.now(),
        end_date__gte=timezone.now()
    )

    voted_elections_ids = Vote.objects.filter(user=request.user).values_list('election_id', flat=True)
    votable_elections = open_elections.exclude(id__in=voted_elections_ids)
    voted_elections = Election.objects.filter(id__in=voted_elections_ids)

    context = {
        'votable_elections': votable_elections,
        'voted_elections': voted_elections,
    }
    return render(request, 'voting/home.html', context)



#  ELECTION VIEWS

def election_list(request):
    """Show all elections (open + closed)"""
    elections = Election.objects.all().order_by('-start_date')
    return render(request, 'voting/election_list.html', {'elections': elections})


@login_required
def candidate_list(request, election_id):
    """Show all candidates for a specific election"""
    election = get_object_or_404(Election, pk=election_id)
    candidates = Candidate.objects.filter(election=election)

    has_voted = Vote.objects.filter(user=request.user, election=election).exists()
    is_open = election.is_open()

    context = {
        'election': election,
        'candidates': candidates,
        'has_voted': has_voted,
        'is_open': is_open,
    }
    return render(request, 'voting/candidate_list.html', context)


@login_required
def vote(request, election_id, candidate_id):
    """Vote for a candidate in an election"""
    election = get_object_or_404(Election, pk=election_id)
    candidate = get_object_or_404(Candidate, pk=candidate_id, election=election)

    # Check if election is open
    if not election.is_open():
        messages.error(request, 'Voting is currently closed for this election.')
        return redirect('candidate_list', election_id=election_id)

    # Check if user has already voted
    if Vote.objects.filter(user=request.user, election=election).exists():
        messages.warning(request, f'You have already voted in the {election.title} election.')
        return redirect('candidate_list', election_id=election_id)

    # Record the vote
    Vote.objects.create(user=request.user, election=election, candidate=candidate)

    messages.success(request, f'Your vote for {candidate.name} has been successfully recorded!')
    return redirect('home')



#  ELECTION RESULTS VIEW


def election_results(request, election_id):
    election = get_object_or_404(Election, id=election_id)
    candidates = Candidate.objects.filter(election=election)
    total_votes = Vote.objects.filter(election=election).count()

    results = []
    for candidate in candidates:
        votes = Vote.objects.filter(candidate=candidate).count()
        percentage = (votes / total_votes) * 100 if total_votes > 0 else 0
        
        results.append({
            'name': candidate.name,
            'vote_count': votes,
            'percentage': percentage,
        })

    return render(request, 'voting/result.html', {
        'election': election,
        'results': results,
        'total_votes': total_votes,
    })

