import json
import locale
import logging
import os
import socket
import threading
import time
import urllib

from gmusicapi.clients.mobileclient import Mobileclient
from gmusicapi.exceptions import CallFailure
from pydub import AudioSegment, effects
import pylru


class Song(object):

    def __init__(self, song_id, loader, artist=None, title=None, albumArtUrl=None, str_rep=None):
        '''
        Constructor

        Keyword arguments:
        song_id -- the unique ID of the song
        loader -- a function taking no arguments which downloads this song and returns its filename
        artist -- the artist. If present, also supply title
        title -- the title. If present, also supply artist
        albumArtUrl -- a URL to the album art
        str_rep -- a readable string representation for this instance. Will be returned for __str__()
        '''
        if not loader:
            raise ValueError("Loader is None")
        if not song_id:
            raise ValueError("Song ID None")

        self.song_id = str(song_id)
        if artist or title:
            if not (artist and title):
                raise ValueError("artist and title have to be supplied together")
        self.artist = artist
        self.title = title
        self.albumArtUrl = albumArtUrl
        self._str_rep = str_rep
        self._loader = loader

    def load(self):
        '''
        Load the song, convert it to wav and return the path to the song file.
        '''
        if not self._loader:
            raise NotImplementedError()

        fname = self._loader()
        # When the song has been loaded, this method can be replaced by a simple method returning the filename
        self.load = lambda: fname
        return fname

    def __repr__(self):
        return self.song_id

    def __str__(self):
        if self._str_rep:
            result = self._str_rep
        elif self.artist and self.title:
            result = "{} - {}".format(self.artist, self.title)
        else:
            result = "Unknown"
        self._str_rep = result
        return result

    def __hash__(self):
        return hash(self.song_id)

    def __eq__(self, other):
        result = self.song_id == other.song_id
        return result

    def __lt__(self, other):
        return self.__str__() < other.__str__()


class AbstractAPI(object):

    _download_semaphore = None
    _conversion_semaphore = None

    def __init__(self, config_dir, config):
        songs_path = os.path.join(".", config.get("song_path", "songs"))

        try:
            if not os.path.isdir(songs_path):
                os.makedirs(songs_path)
        except OSError:
            raise ValueError("Invalid song path: " + songs_path)

        self._config_dir = config_dir
        self._songs_path = songs_path
        self._create_semaphores(config)
        self._loading_ids = set()
        self._loading_ids_lock = threading.Lock()

    def lookup_song(self, song_id):
        '''
        Look up the info about a song based on the song_id.
        Return a Song object.
        '''
        raise NotImplementedError()

    def search_song(self, query, max_fetch=1000):
        '''
        Search for songs.
        Return a list of Song objects.
        The max_fetch argument may or may not determine how many songs are fetched at once.
        '''
        raise NotImplementedError()

    def _get_thread_safe_loader(self, song_id, native_format, download):
        '''
        Return a song loader.

        Keyword arguments:
        song_id -- the song ID
        native_format -- the native format the downloaded file will have (file extension), can be a function
        download -- a function accepting only a target path which downloads the song with the song_id
        '''
        def _loader():
            loading_ids_lock = self._loading_ids_lock
            loading_ids_lock.acquire()
            if song_id in self._loading_ids:
                loading_ids_lock.release()
                time.sleep(0.5)
                return _loader()
            else:
                self._loading_ids.add(song_id)
                loading_ids_lock.release()

            if isinstance(native_format, str):
                _native_format = native_format
            elif hasattr(native_format, "__call__"):
                _native_format = native_format()
            else:
                raise ValueError("native_format has to be a string or a function returning a string")

            songs_path = self._songs_path
            fname = os.path.join(songs_path, ".".join([song_id, "wav"]))
            native_fname = os.path.join(songs_path, ".".join([song_id, _native_format]))

            isfile = os.path.isfile
            if not isfile(fname):
                if not isfile(native_fname):
                    with self._download_semaphore:
                        if not isfile(native_fname):
                            native_fname_tmp = native_fname + ".tmp"
                            if isfile(native_fname_tmp):
                                os.remove(native_fname_tmp)

                            try:
                                download(native_fname_tmp)
                            except Exception as e:
                                logging.getLogger("musicbot").exception("Exception during download")
                                raise e
                            os.rename(native_fname_tmp, native_fname)

                with self._conversion_semaphore:
                    if not isfile(fname):
                        song = AudioSegment.from_file(native_fname, _native_format)
                        song = effects.normalize(song)
                        fname_tmp = fname + ".tmp"
                        if isfile(fname_tmp):
                            os.remove(fname_tmp)
                        song.export(fname_tmp, "wav")
                        os.remove(native_fname)
                        os.rename(fname_tmp, fname)

            loading_ids_lock.acquire()
            self._loading_ids.remove(song_id)
            loading_ids_lock.release()
            return fname
        return _loader

    @classmethod
    def _create_semaphores(cls, config):
        if not cls._download_semaphore or not cls._conversion_semaphore:
            max_downloads = max(config['max_downloads'], 1)
            max_conversions = max(config['max_conversions'], 1)
            cls._download_semaphore = threading.Semaphore(max_downloads)
            cls._conversion_semaphore = threading.Semaphore(max_conversions)


class AbstractSongProvider(AbstractAPI):

    def __init__(self, config_dir, config):
        super().__init__(config_dir, config)

    def get_song(self):
        '''
        Return the next song and remove it from suggestions.
        '''
        raise NotImplementedError()

    def add_played(self, song):
        '''
        Add a song to the list further suggestions are based on it.
        '''
        raise NotImplementedError()

    def get_playlist(self):
        '''
        Return the list suggestions are based on.
        '''
        raise NotImplementedError()

    def remove_from_playlist(self, song):
        '''
        Remove a song from the list suggestions are based on.
        '''
        raise NotImplementedError()

    def get_suggestions(self, max_len):
        '''
        Return a list of suggested songs with the given maximum length.
        '''
        raise NotImplementedError()

    def reload(self):
        '''
        Reload suggestions. Do not drop the playlist.
        '''
        raise NotImplementedError()

    def reset(self):
        '''
        Reset any state and clear the playlist. 
        '''
        raise NotImplementedError()


class GMusicAPI(AbstractSongProvider):
    _api = None
    _songs = pylru.lrucache(256)
    _connect_lock = threading.Lock()

    def __init__(self, config_dir, config, secrets):
        super().__init__(config_dir, config)
        self._ids_path = os.path.join(config_dir, "ids.json")
        self._connect(config, secrets)
        self._quality = config.get("quality", "med")
        self._playlist_id = None
        self._playlist_token = None
        self._station_id = None
        self._last_played_ids = []
        self._suggestions = []
        self._playlist = set()
        self._load_ids()
        self._remote_playlist_load()

    def lookup_song(self, song_id):
        songs = self._songs
        if not song_id:
            raise ValueError("Song ID is None")
        elif song_id in songs:
            return songs[song_id]
        else:
            try:
                info = self._api.get_track_info(song_id)
            except CallFailure:
                return Song(song_id, self._get_loader(song_id))
            return self._song_from_info(info)

    def search_song(self, query, max_fetch=100):
        if not query:
            raise ValueError("query is None")
        max_fetch = min(100, max_fetch)
        results = self._api.search(query, max_fetch)
        _song_from_info = self._song_from_info
        for track in results['song_hits']:
            info = track['track']
            yield _song_from_info(info)

    def set_quality(self, quality):
        if not quality:
            raise ValueError("quality is None")
        quality = quality.strip()
        if quality not in ["hi", "med", "low"]:
            raise ValueError("Quality must be hi, mid or low")
        self._quality = quality

    def get_song(self):
        self._load_suggestions(1)
        song = self._suggestions.pop(0)
        song_id = song.song_id
        self._last_played_ids.append(song_id)
        return song

    def add_played(self, song):
        if song not in self._playlist:
            self._playlist.add(song)
            self._remote_playlist_add(song)
        self._suggestions = list(filter(lambda song: song != song, self._suggestions))
        self._last_played_ids.append(song.song_id)

    def get_playlist(self):
        return self._playlist

    def remove_from_playlist(self, song):
        if song in self._playlist:
            self._remote_playlist_remove(song)
            self._playlist.remove(song)

    def get_suggestions(self, max_len=15):
        if len(self._suggestions) < max_len:
            self._load_suggestions(max_len)

        if len(self._suggestions) > max_len:
            return self._suggestions[:max_len]
        else:
            return self._suggestions

    def reload(self):
        self._suggestions.clear()
        self._remote_playlist_load()

    def reset(self):
        self._remote_playlist_delete()
        self._remote_station_delete()
        self._playlist.clear()
        os.remove(self._ids_path)

    def _load_suggestions(self, max_len):
        self._remote_station_create()
        api_songs = self._api.get_station_tracks(
            self._station_id, recently_played_ids=self._last_played_ids, num_tracks=max(50, max_len))
        if api_songs:
            self._suggestions.extend(map(self._song_from_info, api_songs))
        else:
            song_id = "Tj6fhurtstzgdpvfm4xv6i5cei4"
            fallback_song = Song(song_id, self._get_loader(song_id), "Mickie Krause", "Biste braun kriegste Fraun")
            self._suggestions.append(fallback_song)

    def _remote_playlist_load(self):
        self._remote_playlist_create()
        playlist_contents = self._api.get_all_user_playlist_contents()

        result = set()

        tracks = None
        for playlist in playlist_contents:
            if playlist['id'] == self._playlist_id:
                tracks = playlist['tracks']

        if not tracks:
            return result

        for track in tracks:
            result.add(self._song_from_info(track['track']))

        self._playlist = result

    def _remote_playlist_add(self, song):
        self._remote_playlist_create()
        self._api.add_songs_to_playlist(self._playlist_id, song.song_id)

    def _remote_playlist_remove(self, song):
        self._remote_playlist_create()
        if song in self._playlist:
            playlist_contents = self._api.get_all_user_playlist_contents()

            tracks = None
            for playlist in playlist_contents:
                if playlist['id'] == self._playlist_id:
                    tracks = playlist['tracks']
                    break

            if not tracks:
                return

            track = list(filter(lambda t: t['trackId'] == song.song_id, tracks))
            if not track:
                return

            track = dict(track[0])
            entry_id = track['id']

            self._api.remove_entries_from_playlist(entry_id)

    def _remote_playlist_create(self):
        if not self._playlist_id:
            playlist_name = self._format_playlist_name("BotPlaylist created on {} at {}")
            self._playlist_id = self._api.create_playlist(playlist_name)
            playlists = list(filter(lambda p: p['id'] == self._playlist_id, self._api.get_all_playlists()))
            if not playlists:
                logger = logging.getLogger("musicbot")
                logger.warning("Didn't find playlist that was created a moment ago. (Trying again)")
                time.sleep(0.5)
                playlists = list(filter(lambda p: p['id'] == self._playlist_id, self._api.get_all_playlists()))
                if not playlists:
                    logger.critical("Retry failed!")
                    raise IOError("Could not find created playlist")
            playlist = playlists[0]
            self._playlist_token = playlist['shareToken']
            self._write_ids()

    def _remote_playlist_delete(self):
        self._api.delete_playlist(self._playlist_id)

    def _remote_station_create(self):
        self._remote_playlist_create()
        if not self._station_id:
            station_name = self._format_playlist_name("BotStation created on {} at {}")
            self._station_id = self._api.create_station(station_name, playlist_token=self._playlist_token)
            self._write_ids()

    def _remote_station_delete(self):
        self._api.delete_stations([self._station_id])

    def _load_ids(self):
        if os.path.isfile(self._ids_path):
            with open(self._ids_path, "r") as id_file:
                ids = json.loads(id_file.read())
                id_file.close()
                self._playlist_token = ids.get("playlist_token", None)
                if not self._playlist_token:
                    return
                self._playlist_id = ids.get("playlist_id", None)
                self._station_id = ids.get("station_id", None)

    def _write_ids(self):
        if os.path.isfile(self._ids_path):
            with open(self._ids_path, 'r') as id_file:
                ids = json.loads(id_file.read())
        else:
            ids = {}

        ids['playlist_token'] = self._playlist_token
        ids['playlist_id'] = self._playlist_id
        ids['station_id'] = self._station_id

        with open(self._ids_path, 'w') as id_file:
            id_file.write(json.dumps(ids, indent=4, sort_keys=True))

    @staticmethod
    def _format_playlist_name(name):
        hostname = socket.gethostname()
        timestamp = time.strftime("%c")
        return name.format(hostname, timestamp)

    def _song_from_info(self, info):
        if "storeId" in info:
            song_id = info['storeId']
        else:
            song_id = info['id']
        songs = self._songs
        if song_id in songs:
            return songs[song_id]
        artist = info['artist']
        title = info['title']

        url = None
        if "albumArtRef" in info:
            ref = info["albumArtRef"]
            if ref:
                ref = ref[0]
                if "url" in ref:
                    url = ref["url"]

        song = Song(song_id, self._get_loader(song_id), artist, title, url)
        songs[song_id] = song
        return song

    def _get_loader(self, song_id):
        def _download(path):
            attempts = 3
            url = None
            while attempts and not url:
                try:
                    url = self._api.get_stream_url(song_id, quality=self._quality)
                except CallFailure as e:
                    # Sometimes, the call returns a 403
                    attempts -= 1
                    logger = logging.getLogger("musicbot")
                    logger.error("403, retrying... (%d attempts left)", attempts)
                    if not attempts:
                        logger.exception(e)
                        raise IOError("Can't download song from Google Play")

                request = urllib.request.Request(url)
                with urllib.request.urlopen(request) as page:
                    with open(path, "wb") as file:
                        file.write(page.read())

        return self._get_thread_safe_loader(song_id, "mp3", _download)

    @classmethod
    def _connect(cls, config, secrets):
        locked = cls._connect_lock.acquire(blocking=False)
        try:
            if locked:
                if not cls._api:
                    api = Mobileclient(debug_logging=False)

                    gmusic_locale = config.get('gmusic_locale', locale.getdefaultlocale()[0])

                    try:
                        gmusic_user = secrets["gmusic_username"]
                        gmusic_password = secrets["gmusic_password"]
                        gmusic_device_id = secrets.get("gmusic_device_id", None)
                    except KeyError as e:
                        logger = logging.getLogger("musicbot")
                        logger.critical("Missing GMusic secrets")
                        raise ValueError("Missing secrets key: " + str(e))

                    missing_device_id = not gmusic_device_id
                    if missing_device_id or gmusic_device_id.upper() == "MAC":
                        gmusic_device_id = Mobileclient.FROM_MAC_ADDRESS
                    else:
                        if gmusic_device_id.startswith("0x"):
                            gmusic_device_id = gmusic_device_id[2:]

                    if not api.login(gmusic_user, gmusic_password, gmusic_device_id, gmusic_locale):
                        raise ValueError("Could not log in to GMusic")

                    if missing_device_id:
                        devices = api.get_registered_devices()
                        api.logout()
                        logger = logging.getLogger("musicbot")
                        logger.error("No device ID provided, printing registered devices:")
                        logger.error(json.dumps(devices, indent=4, sort_keys=True))
                        raise ValueError("Missing device ID in secrets")

                    cls._api = api
        finally:
            if locked:
                cls._connect_lock.release()


class YouTubeAPI(AbstractAPI):
    _pafy = __import__("pafy")
    _songs = pylru.lrucache(256)
    _api_key = None

    def __init__(self, config_dir, config, secrets):
        super().__init__(config_dir, config)
        try:
            self._api_key = secrets['youtube_api_key']
        except KeyError:
            raise ValueError("Missing YouTube API key")

    def lookup_song(self, song_id):
        songs = self._songs
        if not song_id:
            raise ValueError("Song ID is None")
        elif song_id in songs:
            return songs[song_id]
        else:
            url = "https://www.youtube.com/watch?v=" + song_id
            video = self._pafy.new(url)
            str_rep = video.title
            url = video.thumb
            song = Song(song_id, self._get_loader(song_id), albumArtUrl=url, str_rep=str_rep)
            songs[song_id] = song
            return song

    def search_song(self, query, max_fetch=50):
        if not query:
            raise ValueError("query is None")
        max_fetch = min(50, max_fetch)
        qs = {
            'q': query,
            'maxResults': max_fetch,
            'safeSearch': "none",
            'part': 'id,snippet',
            'type': 'video',
            'key': self._api_key
        }

        def _track_to_song(track):
            song_id = track['id']['videoId']
            snippet = track['snippet']
            title = snippet['title']

            url = None
            try:
                thumbnails = snippet['thumbnails']
                url = thumbnails['medium']['url']
            except KeyError:
                pass

            return Song(song_id, self._get_loader(song_id), albumArtUrl=url, str_rep=title)

        songs = self._pafy.call_gdata('search', qs)['items']
        for track in songs:
            yield _track_to_song(track)

    def _get_loader(self, song_id):
        audio = None

        def _get_audio_extension():
            nonlocal audio
            url = "https://www.youtube.com/watch?v=" + song_id
            video = self._pafy.new(url)
            audio = video.getbestaudio()
            return audio.extension

        def _download(path):
            audio.download(filepath=path, quiet=True)

        return self._get_thread_safe_loader(song_id, _get_audio_extension, _download)


class SoundCloudAPI(AbstractAPI):
    _soundcloud = __import__("soundcloud")
    _songs = pylru.lrucache(256)
    _client = None
    _connect_lock = threading.Lock()

    def __init__(self, config_dir, config, secrets):
        super().__init__(config_dir, config)
        self._connect(secrets)

    def lookup_song(self, song_id):
        songs = self._songs
        if not song_id:
            raise ValueError("Song ID is None")
        elif song_id in songs:
            return songs[song_id]
        else:
            info = self._client.get("/tracks/{}".format(song_id))
            return self._song_from_info(info)

    def search_song(self, query, max_fetch=200):
        if not query:
            raise ValueError("query is None")
        max_fetch = min(50, max_fetch)
        resource = self._client.get("tracks/", q=query, limit=max_fetch, linked_partitioning=1)
        _info_to_song = self._song_from_info
        while True:
            for info in resource.collection:
                song = _info_to_song(info)
                yield song

            try:
                next_href = resource.next_href
                if not next_href:
                    break
                resource = self._client.get(next_href)
            except AttributeError:
                break

    def _get_loader(self, song_id, stream_url):
        def _download(path):
            url = self._client.get(stream_url, allow_redirects=False).location
            request = urllib.request.Request(url)
            with urllib.request.urlopen(request) as page:
                with open(path, "wb") as file:
                    file.write(page.read())

        return self._get_thread_safe_loader(song_id, "mp3", _download)

    def _song_from_info(self, info):
        song_id = str(info.id)
        songs = self._songs
        if song_id in songs:
            return songs[song_id]
        artist = info.user['username']
        title = info.title
        url = info.artwork_url
        song = Song(song_id, self._get_loader(song_id, info.stream_url), artist, title, url)
        songs[song_id] = song
        return song

    @classmethod
    def _connect(cls, secrets):
        locked = cls._connect_lock.acquire(blocking=False)
        try:
            if locked:
                if not cls._client:
                    app_id = secrets['soundcloud_id']
                    client = cls._soundcloud.Client(client_id=app_id)
                    cls._client = client
        except KeyError:
            raise ValueError("Missing SoundCloud App ID")
        finally:
            if locked:
                cls._connect_lock.release()
