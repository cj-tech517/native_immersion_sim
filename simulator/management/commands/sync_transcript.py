from django.core.management.base import BaseCommand
from youtube_transcript_api import YouTubeTranscriptApi
from simulator.models import VideoContext, TranscriptLine

class Command(BaseCommand):
    help = 'Auto-fetches and populates YouTube transcripts for a given VideoContext ID'

    def add_arguments(self, parser):
        parser.add_argument('video_db_id', type=int, help='The database ID of the VideoContext model')

    def handle(self, *args, **options):
        video_db_id = options['video_db_id']
        
        try:
            # On utilise VideoContext ici !
            video = VideoContext.objects.get(pk=video_db_id)
        except VideoContext.DoesNotExist:
            self.stderr.write(self.style.ERROR(f"VideoContext with ID {video_db_id} does not exist."))
            return

        self.stdout.write(f"Fetching transcript for YouTube ID: {video.youtube_id}...")

        try:
            # Récupération de la transcription via youtube-transcript-api
            api = YouTubeTranscriptApi()
            transcript_list = api.fetch(video.youtube_id)

            # Nettoyage des anciennes lignes pour cette vidéo
            TranscriptLine.objects.filter(video_context=video).delete()

            lines_to_create = []
            for entry in transcript_list:
                text = entry.get('text', '').replace('\n', ' ').strip()
                start_second = int(entry.get('start', 0))

                lines_to_create.append(
                    TranscriptLine(
                        video_context=video, # Le nom exact de ta ForeignKey
                        timestamp_seconds=start_second,
                        text=text
                    )
                )

            TranscriptLine.objects.bulk_create(lines_to_create)
            self.stdout.write(
                self.style.SUCCESS(f"Successfully synced {len(lines_to_create)} transcript lines for '{video.title}'!")
            )

        except Exception as e:
            self.stderr.write(self.style.ERROR(f"Failed to fetch transcript: {str(e)}"))