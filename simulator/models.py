from django.db import models
from django.contrib.auth.models import User
from django.db.models.signals import post_save
from django.dispatch import receiver
from youtube_transcript_api import YouTubeTranscriptApi


class Category(models.Model):
    """Groups content by domain (e.g., Dating, Tech, Culture Lore)."""
    name = models.CharField(max_length=100, unique=True)
    description = models.CharField(
        max_length=1000, 
        blank=True, 
        help_text="Optional description for the category."
    )

    class Meta:
        verbose_name_plural = "Categories"

    def __str__(self):
        return self.name


class ExpressionModule(models.Model):
    """Represents our core textbook tracks (Slangman, BizTalk, Culture Decoder)."""
    MODULE_TYPES = [
        ('SLANG', 'Slangman'),
        ('STREET', 'Street Talk'),
        ('BIZ', 'BizTalk'),
        ('TALK', 'Talk Talk Talk'),
        ('BLEEP', 'Bleep/Taboo'),
        ('DECODER', 'Culture Decoder'),
    ]

    name = models.CharField(max_length=100)
    track_type = models.CharField(max_length=10, choices=MODULE_TYPES)

    def __str__(self):
        return self.name


class VideoContext(models.Model):
    """The video asset the user interacts with."""
    title = models.CharField(max_length=255)
    youtube_id = models.CharField(
        max_length=50, 
        help_text="The 11-character ID at the end of a YouTube link"
    )
    category = models.ForeignKey(
        Category, 
        on_delete=models.PROTECT, 
        related_name='videos'
    )
    expression_modules = models.ManyToManyField(
        ExpressionModule, 
        related_name='videos', 
        blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.title} ({self.category.name})"


class Expression(models.Model):
    """The specific phrase taught in a video, powered by the Native Interpretation Layer."""
    phrase = models.CharField(max_length=255)
    timestamp_seconds = models.PositiveIntegerField(
        help_text="The exact second this phrase appears in the video"
    )

    # The Culture Decoder Layer
    literal_meaning = models.TextField(help_text="What the words mean on the surface.")
    native_subtext = models.TextField(help_text="The REAL hidden meaning native speakers understand.")
    social_context = models.TextField(blank=True, help_text="Why a native speaker uses this.")

    # Relationships
    video_context = models.ForeignKey(
        VideoContext, 
        on_delete=models.CASCADE, 
        related_name='expressions'
    )
    module = models.ForeignKey(
        ExpressionModule, 
        on_delete=models.CASCADE, 
        related_name='expressions'
    )

    def __str__(self):
        return f"'{self.phrase}' in {self.video_context.title}"


class SavedExpression(models.Model):
    MASTERY_CHOICES = [
        ('learning', 'Learning'),
        ('reviewing', 'Reviewing'),
        ('mastered', 'Mastered'),
    ]

    user = models.ForeignKey(
        User, 
        on_delete=models.CASCADE, 
        related_name='saved_expressions'
    )
    expression = models.ForeignKey(
        Expression, 
        on_delete=models.CASCADE, 
        related_name='saved_by_users'
    )
    status = models.CharField(max_length=20, choices=MASTERY_CHOICES, default='learning')
    tags = models.CharField(
        max_length=200, 
        blank=True, 
        help_text="Comma-separated tags e.g. #Sarcasm, #Business"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('user', 'expression')

    def __str__(self):
        return f"{self.user.username} - {self.expression.phrase} [{self.status}]"


class TranscriptLine(models.Model):
    video_context = models.ForeignKey(
        VideoContext, 
        on_delete=models.CASCADE, 
        related_name='transcript_lines'
    )
    timestamp_seconds = models.PositiveIntegerField(help_text="Secondes de début")
    end_seconds = models.PositiveIntegerField(default=0, help_text="Secondes de fin")
    speaker = models.CharField(max_length=100, blank=True, null=True, help_text="e.g. Speaker A")
    text = models.TextField()

    class Meta:
        ordering = ['timestamp_seconds']

    def __str__(self):
        return f"[{self.timestamp_seconds}s - {self.end_seconds}s] {self.text[:30]}..."


# --- User Profile for Manual Approval Workflow ---

class UserProfile(models.Model):
    user = models.OneToOneField(User, on_delete=models.CASCADE)
    is_approved = models.BooleanField(
        default=False, 
        help_text="Designates whether this user has access to the site content."
    )

    def __str__(self):
        return f"Profile of {self.user.username} - Approved: {self.is_approved}"


@receiver(post_save, sender=User)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance, is_approved=False)


# --- Helper Functions ---

def auto_sync_transcript(video):
    """Utility function to attempt automatic YouTube transcript fetching."""
    try:
        raw_transcript = YouTubeTranscriptApi.get_transcript(video.youtube_id)
        
        TranscriptLine.objects.filter(video_context=video).delete()
        
        lines = []
        for item in raw_transcript:
            start = int(item['start'])
            duration = int(item.get('duration', 0))
            lines.append(
                TranscriptLine(
                    video_context=video,
                    timestamp_seconds=start,
                    end_seconds=start + duration,
                    text=item['text'].replace('\n', ' ').strip()
                )
            )
        
        TranscriptLine.objects.bulk_create(lines)
        print(f"Transcript synced successfully for {video.title}")
    except Exception as e:
        print(f"Transcript unavailable via API: {e}")


# --- Dynamic Assessment & Questions Models ---

class VideoAssessment(models.Model):
    """L'évaluation (quiz/devoir) liée à une vidéo spécifique."""
    video_context = models.OneToOneField(
        VideoContext, 
        on_delete=models.CASCADE, 
        related_name='assessment'
    )
    title = models.CharField(max_length=255, default="Video Comprehension Test")
    instructions = models.TextField(blank=True, help_text="Consignes globales de l'exercice.")

    def __str__(self):
        return f"Assessment for: {self.video_context.title}"


class AssessmentQuestion(models.Model):
    """Une question individuelle rattachée à l'évaluation d'une vidéo."""
    QUESTION_TYPES = [
        ('TEXT', 'Réponse libre / Développement (ex: Part 1 & 4)'),
        ('TRUE_FALSE', 'Vrai / Faux avec Justification (ex: Part 2)'),
        ('QCM', 'Question à Choix Multiples (QCM)'),
    ]

    assessment = models.ForeignKey(
        VideoAssessment, 
        on_delete=models.CASCADE, 
        related_name='questions'
    )
    part_number = models.PositiveIntegerField(default=1, help_text="Numéro de la partie (ex: 1 pour Global, 2 pour Détail...)")
    question_text = models.TextField(help_text="Énoncé de la question")
    
    # NEW FIELD FOR AUTO-GRADING
    correct_answer = models.TextField(
        blank=True, 
        help_text="Réponse attendue ou critères de correction pour l'auto-évaluation par l'IA"
    )
    
    question_type = models.CharField(max_length=20, choices=QUESTION_TYPES, default='TEXT')
    points = models.PositiveIntegerField(default=5, help_text="Nombre de points pour cette question")
    
    # Champ pour les options du QCM
    options = models.TextField(
        blank=True, 
        help_text="Entre les options de réponse séparées par un retour à la ligne (pour les QCM)."
    )
    
    # Options additionnelles
    requires_justification = models.BooleanField(default=False, help_text="Cocher si une justification textuelle est exigée (pour le Vrai/Faux)")
    order = models.PositiveIntegerField(default=0, help_text="Ordre d'affichage de la question")

    class Meta:
        ordering = ['part_number', 'order']

    def __str__(self):
        return f"[Part {self.part_number}] {self.question_text[:50]}... ({self.points} pts)"


class StudentAssessmentAttempt(models.Model):
    """Enregistre le score et l'historique des résultats d'un étudiant pour une vidéo."""
    student = models.ForeignKey(User, on_delete=models.CASCADE, related_name='assessment_attempts')
    assessment = models.ForeignKey(VideoAssessment, on_delete=models.CASCADE, related_name='attempts')
    score = models.PositiveIntegerField(help_text="Score obtenu", default=0)
    max_score = models.PositiveIntegerField(default=40)
    submitted_at = models.DateTimeField(auto_now_add=True)
    
    answers_data = models.TextField(blank=True, help_text="Stockage des réponses de l'étudiant (JSON)")
    feedback = models.TextField(blank=True, help_text="Commentaires du professeur sur la copie")
    is_graded = models.BooleanField(default=False, help_text="Cocher si la copie a été corrigée et notée")

    class Meta:
        ordering = ['-submitted_at']

    def __str__(self):
        status = "Corrigé ✅" if self.is_graded else "En attente ⏳"
        return f"{self.student.username} - {self.assessment.title} : {self.score}/{self.max_score} ({status})"