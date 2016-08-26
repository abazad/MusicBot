from _collections_abc import Iterable
import json
import os
import unittest

from musicbot.music_apis import Song, GMusicAPI, YouTubeAPI, SoundCloudAPI


class TestSong(unittest.TestCase):

    def _loader(self):
        return "test.wav"

    def _create_test_songs(self):
        loader = self._loader
        return [Song("testid", loader),
                Song("testid", loader, "testartist", "testtitle"),
                Song("testid", loader, str_rep="testrep"),
                Song("testid", loader, "testartist", "testtitle", str_rep="testrep"),
                Song("testid", loader, "testartist", "testtitle", albumArtUrl="testurl"),
                Song("testid", loader, str_rep="testrep", albumArtUrl="testurl"),
                Song("testid", loader, "testartist", "testtitle", str_rep="testrep", albumArtUrl="testurl")]

    def test_init_missing_required(self):
        with self.assertRaises(ValueError):
            Song(None, self._loader)
        with self.assertRaises(ValueError):
            Song("testid", None)

    def test_init_invalid_values(self):
        with self.assertRaises(ValueError):
            Song("testid", self._loader, "testartist")
        with self.assertRaises(ValueError):
            Song("testid", self._loader, None, "testtitle")

    def test_init_valid(self):
        self._create_test_songs()

    def test_load(self):
        song = Song("testid", self._loader)
        self.assertEqual("test.wav", song.load())

    def test_song_id(self):
        song = Song("testid", self._loader)
        self.assertEqual("testid", song.song_id)

    # Make sure str returns something and doesn't throw errors
    def test_str(self):
        for song in self._create_test_songs():
            self.assertTrue(str(song))


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
            cls.skipTest("Invalid or missing SoundCloud secrets ({})".format(str(e)))

    @classmethod
    def tearDownClass(cls):
        for file in os.listdir("songs"):
            os.remove(os.path.join("songs", file))
        os.rmdir("songs")


if __name__ == "__main__":
    os.chdir("..")
    unittest.main()
