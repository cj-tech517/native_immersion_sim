import json
from django.contrib import admin
from django import forms
from django.shortcuts import render, redirect
from django.urls import path, reverse
from django.contrib import messages
from django.utils.html import format_html
from django.utils.safestring import mark_safe
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.models import User

from .models import (
    Category, 
    ExpressionModule, 
    VideoContext, 
    Expression, 
    SavedExpression, 
    TranscriptLine,
    UserProfile,
    VideoAssessment,
    AssessmentQuestion,
    StudentAssessmentAttempt
)
from .utils import process_srt_file


# 1. Formulaire d'upload SRT
class SRTUploadForm(forms.Form):
    srt_file = forms.FileField(
        label="Fichier .SRT", 
        help_text="Sélectionne le fichier .srt téléchargé"
    )


# 2. Admin pour VideoContext avec l'import SRT
@admin.register(VideoContext)
class VideoContextAdmin(admin.ModelAdmin):
    list_display = ('title', 'category', 'created_at', 'upload_srt_button')
    search_fields = ('title', 'youtube_id')
    list_filter = ('category',)

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:video_id>/upload-srt/', 
                self.admin_site.admin_view(self.upload_srt_view), 
                name='videocontext-upload-srt'
            ),
        ]
        return custom_urls + urls

    def upload_srt_button(self, obj):
        url = reverse('admin:videocontext-upload-srt', args=[obj.id])
        return format_html(
            '<a class="button" style="background-color: #417690; color: white; padding: 3px 10px; border-radius: 4px;" href="{}">Importer SRT</a>', 
            url
        )
    upload_srt_button.short_description = "Action SRT"

    def upload_srt_view(self, request, video_id):
        video = self.get_object(request, video_id)
        if request.method == "POST":
            form = SRTUploadForm(request.POST, request.FILES)
            if form.is_valid():
                count = process_srt_file(video, request.FILES['srt_file'])
                self.message_user(
                    request, 
                    f"Succès ! {count} lignes de transcription ont été importées pour '{video.title}'.", 
                    messages.SUCCESS
                )
                return redirect('admin:simulator_videocontext_changelist')
        else:
            form = SRTUploadForm()

        context = {
            **self.admin_site.each_context(request),
            'form': form,
            'video': video,
            'title': f"Importer un fichier SRT pour : {video.title}",
        }
        return render(request, 'admin/upload_srt.html', context)


# 3. Admin pour la visualisation des lignes de transcription
@admin.register(TranscriptLine)
class TranscriptLineAdmin(admin.ModelAdmin):
    list_display = ('video_context', 'timestamp_seconds', 'end_seconds', 'speaker', 'text')
    list_filter = ('video_context',)
    search_fields = ('text', 'speaker')


# 4. Gestion des Profils Utilisateurs & Validation Manuelle des Abonnés
class UserProfileInline(admin.StackedInline):
    model = UserProfile
    can_delete = False
    verbose_name_plural = 'Statut d\'Abonnement & Accès'

class CustomUserAdmin(UserAdmin):
    inlines = (UserProfileInline,)
    list_display = ('username', 'email', 'first_name', 'last_name', 'is_staff', 'get_is_approved')
    list_select_related = ('userprofile',)

    def get_is_approved(self, obj):
        return obj.userprofile.is_approved
    get_is_approved.boolean = True
    get_is_approved.short_description = "Accès Approuvé"

# Désenregistrement et réenregistrement de l'User admin
admin.site.unregister(User)
admin.site.register(User, CustomUserAdmin)


# 5. Gestion des questions associées directement dans l'admin des devoirs (Inline)
class AssessmentQuestionInline(admin.TabularInline):
    model = AssessmentQuestion
    extra = 1  # Lignes vides par défaut pour ajouter de nouvelles questions
    # Ajout du champ 'options' pour les QCM ici :
    fields = ('part_number', 'question_text', 'question_type', 'options', 'points', 'requires_justification', 'order')


# 6. Enregistrement des devoirs (VideoAssessment)
@admin.register(VideoAssessment)
class VideoAssessmentAdmin(admin.ModelAdmin):
    list_display = ('title', 'video_context')
    search_fields = ('title', 'video_context__title')
    inlines = [AssessmentQuestionInline]


# 7. Enregistrement et configuration avancée des soumissions étudiantes (StudentAssessmentAttempt)
@admin.register(StudentAssessmentAttempt)
class StudentAssessmentAttemptAdmin(admin.ModelAdmin):
    list_display = ('student', 'assessment', 'score', 'max_score', 'is_graded', 'submitted_at')
    list_filter = ('is_graded', 'submitted_at', 'assessment')
    search_fields = ('student__username', 'assessment__title')
    readonly_fields = ('student', 'assessment', 'submitted_at', 'max_score', 'display_answers')
    
    fieldsets = (
        ('Informations de la tentative', {
            'fields': ('student', 'assessment', 'submitted_at', 'max_score')
        }),
        ('Réponses soumises par l\'étudiant', {
            'fields': ('display_answers',)
        }),
        ('Correction et Notation du Professeur', {
            'fields': ('score', 'feedback', 'is_graded'),
            'description': 'Renseigne la note sur le total maximum, ajoute ton feedback et coche la case une fois corrigé.'
        }),
    )

    def display_answers(self, obj):
        """Formate et affiche les réponses avec le texte réel des questions."""
        if not obj.answers_data:
            return "Aucune réponse enregistrée."
        try:
            data = json.loads(obj.answers_data)
            questions_dict = {str(q.id): q for q in obj.assessment.questions.all()}
            
            html = "<ul style='list-style-type: disc; padding-left: 20px;'>"
            for key, val in data.items():
                q_id = key.split('_')[-1]
                question_obj = questions_dict.get(q_id)
                
                q_text = question_obj.question_text if question_obj else key
                part_num = question_obj.part_number if question_obj else "?"
                
                if isinstance(val, dict):
                    ans = val.get('answer', '')
                    justif = val.get('justification', '')
                    html += f"<li style='margin-bottom: 10px;'><b>[Partie {part_num}] {q_text}</b><br>➡️ <b>Réponse :</b> {ans}"
                    if justif:
                        html += f"<br>💡 <em>Justification :</em> {justif}"
                    html += "</li>"
                else:
                    html += f"<li style='margin-bottom: 10px;'><b>[Partie {part_num}] {q_text}</b><br>➡️ <b>Réponse :</b> {val}</li>"
            html += "</ul>"
            
            return format_html("{}", mark_safe(html))
        except Exception as e:
            return f"Erreur de lecture des données : {e}"
    
    display_answers.short_description = "Détails des réponses"


# 8. Enregistrement des autres modèles de base
admin.site.register(Category)
admin.site.register(ExpressionModule)
admin.site.register(Expression)
admin.site.register(SavedExpression)

@admin.register(AssessmentQuestion)
class AssessmentQuestionAdmin(admin.ModelAdmin):
    list_display = ('assessment', 'question_type', 'points')
    list_filter = ('question_type',)