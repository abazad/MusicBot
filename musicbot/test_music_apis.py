import json
import logging
import os
import unittest
from _collections_abc import Iterable

from musicbot.music_apis import Song, GMusicAPI, YouTubeAPI, SoundCloudAPI, AbstractAPI


class TestSong(unittest.TestCase):
    class _TestAPI(AbstractAPI):

        def __init__(self):
            pass

        def get_name(self):
            return "testapi"

        def load_song(self, song):
            return "test.wav"

    def _create_test_songs(self):
        api = TestSong._TestAPI()
        return [Song("testid", api),
                Song("testid", api, "testtitle", "testdescription"),
                Song("testid", api, str_rep="testrep"),
                Song("testid", api, "testtitle", "testdescription", str_rep="testrep"),
                Song("testid", api, "testtitle", "testdescription", albumArtUrl="testurl"),
                Song("testid", api, str_rep="testrep", albumArtUrl="testurl"),
                Song("testid", api, "testtitle", "testdescription", str_rep="testrep", albumArtUrl="testurl"),
                Song("testid", api, "testtitle", "testdescription", str_rep="testrep", albumArtUrl="testurl",
                     duration="42:42")]

    def test_init_missing_required(self):
        with self.assertRaises(ValueError):
            Song(None, TestSong._TestAPI())
        with self.assertRaises(ValueError):
            Song("testid", None)
        with self.assertRaises(ValueError):
            Song(None, None)

    def test_init_valid(self):
        self._create_test_songs()

    def test_load(self):
        song = Song("testid", TestSong._TestAPI())
        self.assertEqual("test.wav", song.load())

    def test_song_id(self):
        song = Song("testid", TestSong._TestAPI())
        self.assertEqual("testid", song.song_id)

    # Make sure str returns something and doesn't throw errors
    def test_str(self):
        for song in self._create_test_songs():
            self.assertTrue(str(song))

    def test_json(self):
        for song in self._create_test_songs():
            self.assertEqual(song, Song.from_json(song.to_json(), {"testapi": TestSong._TestAPI()}))


class APITest(object):
    def test_search_song(self):
        songs = self.api.search_song("kassierer")
        self.assertTrue(songs)
        self.assertTrue(isinstance(songs, Iterable))
        for song in songs:
            self.assertTrue(isinstance(song, Song))
        with self.assertRaises(ValueError):
            list(self.api.search_song(None))

    def test_lookup_song(self):
        song = self.api.lookup_song(self.song_id)
        self.assertTrue(song)
        self.assertTrue(isinstance(song, Song))
        with self.assertRaises(ValueError):
            self.api.lookup_song(None)

    def test_valid_loader(self):
        search_results = self.api.search_song("ok go")
        self.assertTrue(search_results)
        song = search_results.__next__()
        fname = song.load()
        self.assertTrue(os.path.isfile(fname))

    def test_get_name(self):
        name = self.api.get_name()
        self.assertTrue(name)
        self.assertTrue(isinstance(name, str))


class SongProviderTest(object):
    def test_get_song(self):
        api = self.api
        for _ in range(0, 20):
            song = api.get_song()
            self.assertTrue(song)
            self.assertTrue(isinstance(song, Song))

    def test_add_played(self):
        song = self.api.get_song()
        self.api.add_played(song)
        self.assertIn(song, self.api.get_playlist())

    def test_get_playlist(self):
        playlist = self.api.get_playlist()
        self.assertTrue(playlist)
        for song in playlist:
            self.assertTrue(isinstance(song, Song))

    def test_get_suggestions(self):
        suggestions = self.api.get_suggestions(40)
        self.assertTrue(suggestions)

    def reload(self):
        self.api.reload()


class TestGMusicAPI(unittest.TestCase, APITest, SongProviderTest):
    @classmethod
    def setUpClass(cls):
        config_dir = "config"
        with open(os.path.join(config_dir, "config.json"), 'r') as config:
            config = json.loads(config.read())
        with open(os.path.join(config['secrets_location'], "secrets.json"), 'r') as secrets:
            secrets = json.loads(secrets.read())

        cls.song_id = "Ttq2uszcaztntcgnllswbn4pnqy"
        try:
            cls.api = GMusicAPI(config_dir, config, secrets)
        except ValueError as e:
            logging.getLogger("musicbot").warning("GMusic test skipped")
            cls.skipTest("Invalid or missing gmusic secrets ({})".format(str(e)))

    @classmethod
    def tearDownClass(cls):
        cls.api.reset()
        for file in os.listdir("songs"):
            os.remove(os.path.join("songs", file))
        os.rmdir("songs")

    def test_set_quality(self):
        api = self.api
        api.set_quality("hi")
        api.set_quality("med")
        api.set_quality("low")
        with self.assertRaises(ValueError):
            api.set_quality("test")
        with self.assertRaises(ValueError):
            api.set_quality("")
        with self.assertRaises(ValueError):
            api.set_quality(" ")
        with self.assertRaises(ValueError):
            api.set_quality(None)


class TestYoutubeAPI(unittest.TestCase, APITest):
    @classmethod
    def setUpClass(cls):
        config_dir = "config"
        with open(os.path.join(config_dir, "config.json"), 'r') as config:
            config = json.loads(config.read())
        with open(os.path.join(config['secrets_location'], "secrets.json"), 'r') as secrets:
            secrets = json.loads(secrets.read())

        cls.song_id = "NJ1_JpRKeic"
        try:
            cls.api = YouTubeAPI(config_dir, config, secrets)
        except ValueError as e:
            logging.getLogger("musicbot").warning("GMusic test skipped")
            cls.skipTest("Invalid or missing YouTube secrets ({})".format(str(e)))

    @classmethod
    def tearDownClass(cls):
        for file in os.listdir("songs"):
            os.remove(os.path.join("songs", file))
        os.rmdir("songs")


class TestSoundCloudAPI(unittest.TestCase, APITest):
    @classmethod
    def setUpClass(cls):
        config_dir = "config"
        with open(os.path.join(config_dir, "config.json"), 'r') as config:
            config = json.loads(config.read())
        with open(os.path.join(config['secrets_location'], "secrets.json"), 'r') as secrets:
            secrets = json.loads(secrets.read())

        cls.song_id = "160239605"
        try:
            cls.api = SoundCloudAPI(config_dir, config, secrets)
        except ValueError as e:
            logging.getLogger("musicbot").warning("GMusic test skipped")
            cls.skipTest("Invalid or missing SoundCloud secrets ({})".format(str(e)))

    @classmethod
    def tearDownClass(cls):
        for file in os.listdir("songs"):
            os.remove(os.path.join("songs", file))
        os.rmdir("songs")


if __name__ == "__main__":
    os.chdir("..")
    unittest.main()
