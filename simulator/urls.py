from django.urls import path
from django.contrib.auth import views as auth_views
from . import views

urlpatterns = [
    # Authentification & Validation manuelle des abonnés
    path('register/', views.register_view, name='register'),
    path('login/', views.login_view, name='login'),
    path('logout/', auth_views.LogoutView.as_view(next_page='login'), name='logout'),
    path('pending-approval/', views.pending_approval_view, name='pending_approval'),

    # Routes principales du simulateur (protégées par approved_required)
    path('', views.video_index, name='video_index'),
    path('video/<int:video_id>/', views.video_player, name='video_player'),
    path('bookmark/<int:expression_id>/', views.toggle_bookmark, name='toggle_bookmark'),
    path('my-deck/', views.my_deck, name='my_deck'),
    path('quiz/', views.practice_quiz, name='practice_quiz'),
    path('update-mastery/<int:expression_id>/', views.update_mastery, name='update_mastery'),
    path('video/<int:video_id>/assessment/', views.video_assessment_view, name='video_assessment'),
    path('my-scores/', views.student_dashboard, name='student_dashboard'),
    path('about/', views.about_us_view, name='about_us'), # <-- Add this line

    # API Route pour l'agent IA RAG (Smart Agent Chat)
    path('api/ai-chat/', views.ai_chat_api, name='ai_chat_api'),
    path('ai-coach/', views.ai_coach_page, name='ai_coach_page'),
    path('student/attempt/<int:attempt_id>/', views.student_attempt_detail, name='student_attempt_detail'),
]