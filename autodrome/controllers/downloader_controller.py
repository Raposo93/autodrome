from autodrome.logger import logger

class DownloaderController:
    def __init__(self, downloader, metadata_service, organizer):
        self.downloader = downloader
        self.metadata_service = metadata_service
        self.organizer = organizer
        
    def download_and_tag(self, playlist_url, artist, album, release_id, track_count=None):
        logger.debug(f"download_and_tag release_id: {release_id}")
        tracks = self.metadata_service.get_tracks(release_id)
        
        with self.downloader.create_temp_folder() as tmpdir:
            self.downloader.download_playlist(playlist_url, tmpdir, total=track_count)
            cover_path = self.metadata_service.get_cover_art(release_id)
            self.organizer.tag_and_rename(tmpdir, artist, album, tracks, cover_path)
            self.organizer.move_to_library(tmpdir, artist, album)
