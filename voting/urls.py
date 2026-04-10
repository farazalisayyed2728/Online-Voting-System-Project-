from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    path('', views.home, name='home'),
    path('elections/', views.election_list, name='election_list'),

    # Auth
    path('register/', views.register, name='register'),
    path('login/', views.CustomLoginView.as_view(), name='login'),
    path('logout/', auth_views.LogoutView.as_view(template_name='voting/logout.html'), name='logout'),

    # Voting
    path('election/<int:election_id>/', views.candidate_list, name='candidate_list'),
    path('election/<int:election_id>/vote/<int:candidate_id>/', views.vote, name='vote'),

    # Results
    path('election/<int:election_id>/results/', views.election_results, name='election_results'),
    path('election/<int:election_id>/vote/<int:candidate_id>/', views.vote, name='vote')

    
]
   