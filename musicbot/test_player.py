import json
import os
import time
import unittest

from musicbot.music_apis import Song, AbstractSongProvider, GMusicAPI
from musicbot.player import SongQueue, Player


class TestSongProvider(AbstractSongProvider):

    def __init__(self, loader):
        self._loader = loader
        self.counter = 0

    def get_song(self):
        song_id = "test" + str(self.counter)
        song = Song(song_id, self._loader(song_id))
        self.counter += 1
        return song

    def get_suggestions(self, max_len):
        songs = []
        for i in range(0, max_len):
            song_id = "test" + str(i + self.counter)
            song = Song(song_id, self._loader(song_id))
            songs.append(song)
        return songs


class TestSongQueue(unittest.TestCase):

    @classmethod
    def _loader(cls, song_id):
        def _loader():
            cls.loaded.add(song_id)
            return song_id + ".wav"
        return _loader

    @classmethod
    def setUpClass(cls):
        cls.song_provider = TestSongProvider(cls._loader)
        cls.loaded = set()
        song = cls.song_provider.get_suggestions(1)[0]
        cls.queue = SongQueue(cls.song_provider)
        while song.song_id not in cls.loaded:
            time.sleep(0.2)

    @classmethod
    def tearDownClass(cls):
        cls.queue.close()

    def test_pop(self):
        first_song = Song("testidpop", self._loader("testidpop"))
        self.queue.append(first_song)
        found = False
        time.sleep(0.2)
        for _ in range(0, 10):
            song = self.queue.pop(0)
            if song == first_song:
                found = True
            self.assertTrue(song)
            self.assertTrue(isinstance(song, Song))
        self.assertTrue(found)
        self.assertIn(first_song.song_id, self.loaded)

    def test_append(self):
        song = Song("testidappend", self._loader("testidappend"))
        queue = self.queue
        queue.append(song)
        attempts = 10
        while song not in queue and attempts:
            time.sleep(0.2)
            attempts -= 1
        self.assertTrue(song.song_id in self.loaded)

        queue.append(song)
        time.sleep(0.5)
        self.assertTrue(len(list(filter(lambda song: song == song, self.queue))) == 1)


class TestPlayer(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        config_dir = "config"
        with open(os.path.join(config_dir, "config.json"), 'r') as config:
            config = json.loads(config.read())
        with open(os.path.join(config['secrets_location'], "secrets.json"), 'r') as secrets:
            secrets = json.loads(secrets.read())
        api = GMusicAPI(config_dir, config, secrets)
        cls.api = api
        api.add_played(api.get_song())
        api.reload()
        cls.player = Player(api)
        cls.player.run()
        with cls.player._lock:
            pass

    @classmethod
    def tearDownClass(cls):
        cls.player.close()
        cls.api.reset()
        time.sleep(0.5)
        for file in os.listdir("songs"):
            os.remove(os.path.join("songs", file))
        os.rmdir("songs")

    def test_skip_song(self):
        song = self.api.get_song()
        self.player.queue(song)
        while(song not in self.player.get_queue()):
            time.sleep(0.2)
        self.player.skip_song(song)
        self.assertNotIn(song, self.player.get_queue())

    def test_next(self):
        player = self.player
        while(not player.get_current_song()):
            time.sleep(0.2)
        current_song = player.get_current_song()
        self.assertTrue(current_song)
        player.next()

        attempts = 30
        while current_song == player.get_current_song() and attempts:
            time.sleep(0.2)
            attempts -= 1

        self.assertNotEqual(current_song, player.get_current_song())

if __name__ == "__main__":
    os.chdir("..")
    unittest.main()
