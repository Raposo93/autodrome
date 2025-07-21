from mutagen.mp3 import MP3
from mutagen.id3 import ID3, APIC, error
from autodrome.logger import logger

class CoverEmbedder:
    def embed_cover(
        self,
        mp3_file_path: str,
        cover_image_path: str
    ) -> None:
        audio = MP3(mp3_file_path, ID3=ID3)

        try:
            audio.add_tags()
        except error:
            pass
        
        with open(cover_image_path, 'rb') as img:
            audio.tags.add(
                APIC(
                    encoding=3,          # UTF-8
                    mime='image/jpeg',
                    type=3,              # Cover(front)
                    desc='Cover',
                    data=img.read()
                )
            )
        audio.save()
