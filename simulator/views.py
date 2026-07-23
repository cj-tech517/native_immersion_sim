import json
from functools import wraps
from django.contrib import messages
from django.contrib.auth import authenticate, login
from django.contrib.auth.decorators import login_required
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.core.paginator import Paginator
from django.db.models import Q, Max
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST
from django.views.decorators.csrf import csrf_exempt

from google import genai
from google.genai import types

from .models import (
    Category,
    Expression,
    SavedExpression,
    TranscriptLine,
    VideoContext,
    VideoAssessment,
    StudentAssessmentAttempt,
)

# Initialize the Gemini client using your API key
client = genai.Client(api_key=AI_API_KEY)


# --- Décorateur personnalisé : Vérifie si le compte est approuvé ---
def approved_required(view_func):
    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect('login')
        
        if request.user.is_superuser:
            return view_func(request, *args, **kwargs)
            
        if hasattr(request.user, 'userprofile') and request.user.userprofile.is_approved:
            return view_func(request, *args, **kwargs)
            
        return redirect('pending_approval')
    return _wrapped_view


# --- Vues d'Authentification & Validation ---

def register_view(request):
    if request.user.is_authenticated:
        return redirect('video_index')
        
    if request.method == 'POST':
        form = UserCreationForm(request.POST)
        if form.is_valid():
            user = form.save()
            login(request, user)
            return redirect('pending_approval')
    else:
        form = UserCreationForm()
    return render(request, 'simulator/register.html', {'form': form})


def login_view(request):
    if request.user.is_authenticated:
        if request.user.is_superuser or (hasattr(request.user, 'userprofile') and request.user.userprofile.is_approved):
            return redirect('video_index')
        return redirect('pending_approval')

    if request.method == 'POST':
        form = AuthenticationForm(request, data=request.POST)
        if form.is_valid():
            user = form.get_user()
            login(request, user)
            
            if user.is_superuser or (hasattr(user, 'userprofile') and user.userprofile.is_approved):
                return redirect('video_index')
            else:
                return redirect('pending_approval')
    else:
        form = AuthenticationForm()
    return render(request, 'simulator/login.html', {'form': form})


@login_required
def pending_approval_view(request):
    if request.user.is_superuser or (hasattr(request.user, 'userprofile') and request.user.userprofile.is_approved):
        return redirect('video_index')
    return render(request, 'simulator/pending_approval.html')


# --- Vues du Simulateur (Protégées par approved_required) ---

@approved_required
def video_index(request):
    categories = Category.objects.all()
    videos = VideoContext.objects.all().select_related('category')

    category_id = request.GET.get('category')
    if category_id and category_id.isdigit():
        videos = videos.filter(category_id=category_id)

    query = request.GET.get('q', '').strip()
    if query:
        videos = videos.filter(
            Q(title__icontains=query) | 
            Q(category__name__icontains=query) |
            Q(expressions__phrase__icontains=query)
        ).distinct()

    paginator = Paginator(videos, 12)
    page_number = request.GET.get('page')
    page_obj = paginator.get_page(page_number)

    saved_items_count = 0
    if request.user.is_authenticated:
        saved_items_count = SavedExpression.objects.filter(user=request.user).count()

    context = {
        'categories': categories,
        'videos': page_obj,
        'selected_category': int(category_id) if category_id and category_id.isdigit() else None,
        'search_query': query,
        'saved_items_count': saved_items_count,
    }
    return render(request, 'simulator/index.html', context)


@approved_required
def video_player(request, video_id):
    video = get_object_or_404(VideoContext, id=video_id)
    expressions = video.expressions.all().order_by('timestamp_seconds')
    transcript_lines = video.transcript_lines.all().order_by('timestamp_seconds')
    
    context = {
        'video': video,
        'expressions': expressions,
        'transcript_lines': transcript_lines,
    }
    return render(request, 'simulator/player.html', context)


@require_POST
@approved_required
def toggle_bookmark(request, expression_id):
    expression = get_object_or_404(Expression, id=expression_id)
    saved, created = SavedExpression.objects.get_or_create(user=request.user, expression=expression)

    if not created:
        saved.delete()
        return JsonResponse({'status': 'unbookmarked', 'is_saved': False})
    
    return JsonResponse({'status': 'bookmarked', 'is_saved': True})


@approved_required
def my_deck(request):
    query = request.GET.get('q', '')
    status_filter = request.GET.get('status', '')

    saved_items = SavedExpression.objects.filter(user=request.user).select_related('expression__video_context')

    if query:
        saved_items = saved_items.filter(
            Q(expression__phrase__icontains=query) | 
            Q(expression__native_subtext__icontains=query)
        )

    if status_filter:
        saved_items = saved_items.filter(status=status_filter)

    context = {
        'saved_items': saved_items,
        'query': query,
        'selected_status': status_filter,
    }
    return render(request, 'simulator/my_deck.html', context)


@approved_required
def practice_quiz(request):
    saved_items = SavedExpression.objects.filter(user=request.user).select_related('expression', 'expression__video_context')
    context = {
        'saved_items': saved_items,
    }
    return render(request, 'simulator/quiz.html', context)


@require_POST
@approved_required
def update_mastery(request, expression_id):
    saved_item = get_object_or_404(SavedExpression, user=request.user, expression_id=expression_id)
    new_status = request.POST.get('status')

    if new_status:
        saved_item.status = new_status
    else:
        saved_item.status = 'mastered' if saved_item.status == 'learning' else 'learning'

    saved_item.save()
    return JsonResponse({'status': 'success', 'new_status': saved_item.status})


@approved_required
def video_assessment_view(request, video_id):
    video = get_object_or_404(VideoContext, id=video_id)
    assessment = get_object_or_404(VideoAssessment, video_context=video)

    existing_attempts_count = StudentAssessmentAttempt.objects.filter(
        student=request.user, 
        assessment=assessment
    ).count()

    if request.method == 'POST':
        if existing_attempts_count >= 3:
            messages.error(request, "Tu as atteint le nombre maximum de 3 essais pour cette évaluation.")
            return redirect('student_dashboard')

        answers = {}
        total_max_score = 0
        
        for question in assessment.questions.all():
            total_max_score += question.points
            q_key = f'question_{question.id}'
            
            if question.question_type == 'TRUE_FALSE':
                ans_bool = request.POST.get(f'{q_key}_bool', '')
                ans_justif = request.POST.get(f'{q_key}_justification', '')
                answers[q_key] = {
                    'type': 'TRUE_FALSE',
                    'answer': ans_bool,
                    'justification': ans_justif
                }
            else:
                ans_text = request.POST.get(q_key, '')
                answers[q_key] = {
                    'type': question.question_type,
                    'answer': ans_text
                }

        max_score = total_max_score if total_max_score > 0 else 40

        # Create the attempt record
        new_attempt = StudentAssessmentAttempt.objects.create(
            student=request.user,
            assessment=assessment,
            score=0,  
            max_score=max_score,
            answers_data=json.dumps(answers),
            is_graded=False,
            feedback=""
        )
        
        # Trigger the AI Auto-Grader instantly on submission
        evaluate_student_attempt_with_ai(new_attempt.id)
        
        messages.success(request, "Évaluation soumise et corrigée instantanément par l'IA !")
        return redirect('student_dashboard')

    context = {
        'video': video,
        'assessment': assessment,
        'attempts_count': existing_attempts_count,
    }
    return render(request, 'simulator/assessment.html', context)


@approved_required
def ai_coach_page(request):
    return render(request, 'simulator/ai_coach.html')


# --- Unified AI Fluency Coach API (RAG Agent) ---

@csrf_exempt
@approved_required
def ai_chat_api(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            user_query = data.get("question", "").strip()
            
            if not user_query:
                return JsonResponse({"error": "Question cannot be empty"}, status=400)

            # 1. SMART SCAN: Look through transcript text for matching keywords
            keywords = user_query.split()
            query_filter = Q()
            for word in keywords:
                if len(word) > 3:
                    query_filter |= Q(text__icontains=word) | Q(speaker__icontains=word)
            
            matched_lines = TranscriptLine.objects.filter(query_filter).select_related('video_context')[:10]
            
            script_context = ""
            for line in matched_lines:
                script_context += f"[{line.video_context.title} at {line.timestamp_seconds}s] {line.speaker or 'Speaker'}: {line.text}\n"
            
            agent_persona = (
                "You are an elite English Fluency AI Coach for advanced C1/C2 students. "
                "You have absolute access to all video scripts in the app. "
                "Use the provided Script Context to precisely answer the user's question about what "
                "characters meant, their underlying emotions, idioms, or cultural nuances. "
                "Never give simple definitions. Provide nuance, emotional tone, and 2 advanced synonyms."
            )
            
            full_prompt = f"Script Context:\n{script_context}\n\nUser Question: {user_query}"

            response = client.models.generate_content(
                model='gemini-3.6-flash',
                contents=full_prompt,
                config=types.GenerateContentConfig(system_instruction=agent_persona)
            )

            sources = list(set([line.video_context.title for line in matched_lines]))

            return JsonResponse({
                "reply": response.text,
                "sources_used": sources
            })
            
        except Exception as e:
            print(f"AI Chat Error: {str(e)}")
            return JsonResponse({"reply": f"An error occurred: {str(e)}"}, status=500)
            
    return JsonResponse({"error": "Only POST requests allowed"}, status=400)


@approved_required
def student_dashboard(request):
    """Tableau de bord étudiant affichant l'historique complet de toutes les tentatives."""
    all_attempts = StudentAssessmentAttempt.objects.filter(
        student=request.user
    ).select_related(
        'assessment', 
        'assessment__video_context', 
        'assessment__video_context__category'
    ).order_by('-submitted_at')
    
    context = {
        'attempts': all_attempts,
    }
    return render(request, 'simulator/student_dashboard.html', context)


@approved_required
def student_attempt_detail(request, attempt_id):
    """Affiche le détail d'une tentative spécifique avec les réponses de l'étudiant et les retours."""
    attempt = get_object_or_404(
        StudentAssessmentAttempt.objects.select_related('assessment', 'assessment__video_context'),
        id=attempt_id,
        student=request.user
    )
    
    # Parse the JSON answers stored during submission
    parsed_answers = {}
    try:
        if attempt.answers_data:
            parsed_answers = json.loads(attempt.answers_data)
    except json.JSONDecodeError:
        parsed_answers = {}

    # Map questions with student answers for easy template rendering
    questions_breakdown = []
    for question in attempt.assessment.questions.all():
        q_key = f'question_{question.id}'
        student_response = parsed_answers.get(q_key, {})
        questions_breakdown.append({
            'question': question,
            'student_answer': student_response.get('answer', ''),
            'student_justification': student_response.get('justification', ''),
            'question_type': question.question_type,
        })

    context = {
        'attempt': attempt,
        'questions_breakdown': questions_breakdown,
    }
    return render(request, 'simulator/student_attempt_detail.html', context)


def evaluate_student_attempt_with_ai(attempt_id):
    """Évalue automatiquement toutes les questions d'une tentative en un seul appel groupé à l'API Gemini."""
    attempt = StudentAssessmentAttempt.objects.select_related('assessment', 'assessment__video_context').get(id=attempt_id)
    assessment = attempt.assessment
    
    try:
        student_answers = json.loads(attempt.answers_data) if attempt.answers_data else {}
    except json.JSONDecodeError:
        student_answers = {}

    questions = assessment.questions.all()
    total_score = 0
    max_score = 0
    evaluation_summary = []

    # Build a structured payload of all questions and student answers
    payload_data = []
    for question in questions:
        max_score += question.points
        q_key = f'question_{question.id}'
        response_data = student_answers.get(q_key, {})
        
        payload_data.append({
            "question_id": question.id,
            "part_number": question.part_number,
            "question_text": question.question_text,
            "max_points": question.points,
            "expected_answer": question.correct_answer or "Evaluate based on comprehension, nuance, and accuracy.",
            "student_answer": response_data.get('answer', ''),
            "student_justification": response_data.get('justification', '')
        })

    grading_prompt = f"""
    You are an elite C1/C2 English immersion coach and AI examiner.
    Evaluate the following student assessment submission based on the provided questions, max points, and expected criteria.
    
    Submission Data:
    {json.dumps(payload_data, ensure_ascii=False, indent=2)}
    
    Provide your evaluation strictly in valid JSON format as a list of objects, where each object corresponds to a question ID and contains:
    1. "question_id": (integer matching the input)
    2. "points_awarded": (integer between 0 and the respective question's max_points)
    3. "comment": (short constructive feedback in French explaining the grade, pointing out strengths and areas to improve)
    
    Format example:
    [
      {{"question_id": 1, "points_awarded": 4, "comment": "Bonne compréhension globale..."}},
      ...
    ]
    """

    try:
        ai_response = client.models.generate_content(
            model='gemini-3.6-flash',
            contents=grading_prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        
        results = json.loads(ai_response.text)
        
        # Map results back by question_id
        results_map = {item.get("question_id"): item for item in results}
        
        for question in questions:
            res = results_map.get(question.id, {})
            awarded = int(res.get("points_awarded", 0))
            # Ensure awarded points don't exceed max points
            awarded = min(max(0, awarded), question.points)
            comment = res.get("comment", "Évaluation validée.")
            
            total_score += awarded
            evaluation_summary.append(f"• Question {question.part_number} ({awarded}/{question.points} pts) : {comment}")
            
    except Exception as e:
        # Fallback graceful handling if quota is exceeded or technical error occurs
        error_msg = str(e)
        if "429" in error_msg:
            fallback_comment = "Évaluation automatique temporairement suspendue (Quota journalier de l'API atteint). En attente de révision manuelle."
        else:
            fallback_comment = f"Erreur technique lors de l'évaluation automatique: {error_msg}"
            
        for question in questions:
            evaluation_summary.append(f"• Question {question.part_number} (0/{question.points} pts) : {fallback_comment}")
        total_score = 0

    # Save final results
    attempt.score = total_score
    attempt.max_score = max_score if max_score > 0 else 40
    attempt.is_graded = True
    attempt.feedback = "\n".join(evaluation_summary)
    attempt.save()
    
    return attempt


def about_us_view(request):
    """Renders the About Us page."""
    return render(request, 'simulator/about.html')


















