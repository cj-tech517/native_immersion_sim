import re
from .models import TranscriptLine

def parse_srt_time(time_str):
    """Convertit '00:01:23,456' en secondes totales (ex: 83)."""
    hours, minutes, seconds = time_str.replace(',', '.').split(':')
    return int(int(hours) * 3600 + int(minutes) * 60 + float(seconds))

def process_srt_file(video_instance, srt_file):
    """Lit le fichier .srt et crée les objets TranscriptLine."""
    # Décodage du fichier (utf-8-sig gère les encodages Windows et Mac)
    content = srt_file.read().decode('utf-8-sig', errors='ignore')

    # Regex pour capturer : Début --> Fin \n Texte
    pattern = re.compile(
        r'\d+\r?\n(\d{2}:\d{2}:\d{2},\d{3})\s*-->\s*(\d{2}:\d{2}:\d{2},\d{3})\r?\n([\s\S]*?)(?=\r?\n\d+\r?\n|\Z)'
    )
    matches = pattern.findall(content)

    # Nettoyage des anciens sous-titres pour cette vidéo
    TranscriptLine.objects.filter(video_context=video_instance).delete()

    lines_to_create = []
    for start_time, end_time, text_block in matches:
        start_sec = parse_srt_time(start_time)
        end_sec = parse_srt_time(end_time)
        clean_text = text_block.replace('\r', '').replace('\n', ' ').strip()

        # Extrait le locuteur s'il est noté sous la forme [Speaker A]: texte
        speaker = ""
        speaker_match = re.match(r'^\[(.*?)\]\s*(.*)', clean_text)
        if speaker_match:
            speaker = speaker_match.group(1)
            clean_text = speaker_match.group(2)

        lines_to_create.append(
            TranscriptLine(
                video_context=video_instance,
                timestamp_seconds=start_sec,
                end_seconds=end_sec,
                speaker=speaker,
                text=clean_text
            )
        )

    # Insertion rapide en lot
    TranscriptLine.objects.bulk_create(lines_to_create)
    return len(lines_to_create)