from yt_api import YTApi
from metadata_service import MetadataService
from downloader import Downloader
from organizer import Organizer
from logger import logger

class Autodrome:
    def __init__(self, yt_api, metadata_service, downloader, organizer):
        self.yt_api = yt_api
        self.metadata_service = metadata_service
        self.downloader = downloader
        self.organizer = organizer
    
    def run(self):
        artist = input("Enter artist name: ").strip()
        album = input("Enter album name: ").strip()

        if not artist and not album:
            logger.error("Artist and album missing. Exiting")
            return
        
        query = f"{artist} {album}"
        playlists = self.yt_api.search_playlist(query)
        if not playlists:
            logger.error("No playlist found")
            return
        
        self.show_playlists(playlists)
        selected = self.select_playlist(playlists)
        if not selected:
            logger.warning("No playlist selected")
            return
        
        releases = self.metadata_service.search_releases(artist, album)
        # print(f"releases: {releases}")
        if not releases:
            logger.error("No releases found")
            return
        
        self.show_releases(releases)
        
        release = self.select_release(releases)
        if not release:
            logger.warning("No release selected")
            return
            
        tracks = self.metadata_service.get_tracks(release.id)
        cover_path = self.metadata_service.get_cover_art(release.id)

        destination = "."
        
        temp_dir = self.downloader.create_temp_folder()
        try:
            self.downloader.download_playlist(selected.url, temp_dir.name)
            self.organizer.tag_and_rename(temp_dir.name, release.artist, release.title, tracks, cover_path)
            self.organizer.move_to_library(temp_dir.name, release.artist, release.title, destination)
        finally:
            temp_dir.cleanup()

        logger.info("Finished successfully")
    
    def show_playlists(self, playlists):
        for i, pl in enumerate(playlists):
            print(f"[{i}] {pl.title} - {pl.track_count or '?'} tracks - {pl.url}")

    def select_playlist(self, playlists):
        idx = input("Choose a playlist number: ").strip()
        if idx.isdigit() and int(idx) < len(playlists):
            return playlists[int(idx)]
        return None

    def show_releases(self, releases):
        for i, release in enumerate(releases):
            tracks = self.metadata_service.get_tracks(release.id)
            print(f"[{i}] {release.title} ({release.date}) - {len(tracks)} tracks")
            
    def select_release(self, releases):
        idx = input("Choose a release number: ").strip()
        if idx.isdigit() and int(idx) < len(releases):
            return releases[int(idx)]
        return None
    
yt_api = YTApi()
metadata_service = MetadataService()
downloader = Downloader()
organizer = Organizer()

# Instanciar Autodrome con estos objetos
autodrome = Autodrome(yt_api, metadata_service, downloader, organizer)
autodrome.run()