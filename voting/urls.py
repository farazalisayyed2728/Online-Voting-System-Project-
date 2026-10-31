from django.contrib.auth import views as auth_views
from django.urls import path

from . import api, views

urlpatterns = [
    path("", views.home, name="home"),
    path("elections/", views.election_list, name="election_list"),
    path("manage/", views.admin_dashboard, name="admin_dashboard"),
    path("notifications/", views.notification_list, name="notifications"),
    path("register/", views.register, name="register"),
    path("login/", views.CustomLoginView.as_view(), name="login"),
    path(
        "logout/",
        auth_views.LogoutView.as_view(template_name="voting/logout.html"),
        name="logout",
    ),
    path("email/verify/<uuid:token>/", views.verify_email, name="verify_email"),
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(template_name="voting/password_reset.html"),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="voting/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset/confirm/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="voting/password_reset_confirm.html"
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset/complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="voting/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    path("election/<int:election_id>/", views.candidate_list, name="candidate_list"),
    path("election/<int:election_id>/confirm/", views.confirm_vote, name="confirm_vote"),
    path("election/<int:election_id>/vote/", views.cast_vote, name="cast_vote"),
    path(
        "election/<int:election_id>/results/",
        views.election_results_view,
        name="election_results",
    ),
    path(
        "election/<int:election_id>/publish-results/",
        views.publish_election_results,
        name="publish_results",
    ),
    path("api/v1/elections/", api.ElectionListAPI.as_view(), name="api_elections"),
    path(
        "api/v1/elections/<int:election_id>/candidates/",
        api.CandidateListAPI.as_view(),
        name="api_candidates",
    ),
    path(
        "api/v1/elections/<int:election_id>/vote/",
        api.CastBallotAPI.as_view(),
        name="api_vote",
    ),
    path(
        "api/v1/elections/<int:election_id>/results/",
        api.ElectionResultsAPI.as_view(),
        name="api_results",
    ),
    path("api/v1/dashboard/", api.DashboardAPI.as_view(), name="api_dashboard"),
    path(
        "api/v1/admin/analytics/",
        api.AdminAnalyticsAPI.as_view(),
        name="api_admin_analytics",
    ),
]
