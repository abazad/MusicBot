#  -*- coding: utf-8 -*-
class Player(object):

    def __init__(self):
        import pyglet
        self.playing = False
        self._pyglet = pyglet
        self._player = pyglet.media.Player()
        self._queue = []
        self._player.set_handler("on_player_eos", self._on_eos)

    def queue(self, store_id, fname):
        res = self._pyglet.media.load(fname)
        self._queue.append({"store_id": store_id, "res": res})
        if not self.playing:
            self._on_eos()

    def get_queue(self):
        return list(map(lambda song: song["store_id"], self._queue))

    '''
    Needs argument store_id or queue_position
    '''

    def skip_song(self, **kwargs):
        if "store_id" in kwargs:
            store_id = kwargs["store_id"]
            self._queue = list(
                filter(lambda song: song["store_id"] != store_id))
        elif "queue_position" in kwargs:
            pos = kwargs["queue_position"]
            self._queue.pop(pos)

    def pause(self):
        self._player.pause()

    def resume(self):
        self._player.play()

    def next(self):
        self._player.next_source()

    def _on_eos(self):
        if len(self._queue) > 0:
            song = self._queue.pop(0)
            self._player.queue(song["res"])
            self._player.play()
            self.playing = True
        else:
            self.playing = False

    def run(self):
        self._pyglet.app.run()

    def close(self):
        self._player.delete()
        self._pyglet.app.exit()
