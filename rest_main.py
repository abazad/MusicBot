import os
import signal
import ssl

from aiohttp import web
from aiohttp_wsgi import WSGIHandler

import main
from musicbot import rest_api

rest_api.init(main.apis, main.queued_player)

cert_path = "config/ssl.cert"
key_path = "config/ssl.key"
if not (os.path.isfile(cert_path) and os.path.isfile(key_path)):
    print("MISSING SSL FILES (ssl.cert and ssl.key in config directory)")
    os.kill(os.getpid(), signal.SIGINT)

try:
    wsgi_handler = WSGIHandler(rest_api.__hug_wsgi__)
    app = web.Application()
    app.router.add_route("*", "/{path_info:.*}", wsgi_handler)
    sslcontext = ssl.SSLContext(ssl.PROTOCOL_SSLv23)

    password = input("Enter SSL key password: ")
    sslcontext.load_cert_chain(cert_path, key_path, password=password)
    main.run()
    web.run_app(app, ssl_context=sslcontext)
    print("EXITING...")
    main.queued_player.close()
except:
    pass
os.kill(os.getpid(), signal.SIGINT)
