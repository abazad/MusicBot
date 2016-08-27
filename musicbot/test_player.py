import os
import unittest

from musicbot.music_apis import Song, AbstractSongProvider
from musicbot.player import SongQueue
import test_logger


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
            return song_id + ".wav"
        return _loader

    def setUp(self):
        self.queue = SongQueue(self.song_provider)

    @classmethod
    def setUpClass(cls):
        cls.song_provider = TestSongProvider(cls._loader)

    def tearDown(self):
        self.queue.close()

    def test_pop(self):
        first_song = Song("testidpop", self._loader("testidpop"))
        self.queue.append(first_song)
        song = self.queue.pop(0)
        self.assertTrue(song == first_song)

    def test_empty_pop(self):
        song = self.queue.pop(0)
        self.assertTrue(song)
        self.assertTrue(isinstance(song, Song))

    def test_append(self):
        song = Song("testidappend1", self._loader("testidappend1"))
        song2 = Song("testidappend2", self._loader("testidappend2"))
        queue = self.queue

        queue.append(song)
        self.assertTrue(song in queue)
        queue.append(song2)
        self.assertTrue(song2 in queue)

    def test_append_duplicate(self):
        song = Song("testidappenddup", self._loader("testidappenddup"))
        queue = self.queue
        queue.append(song)
        self.assertTrue(song in queue)

        queue.append(song)
        self.assertTrue(len(list(filter(lambda song: song == song, self.queue))) == 1)


if __name__ == "__main__":
    os.chdir("..")
    unittest.main()
