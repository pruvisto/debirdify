"""
WSGI config for debirdify project.

It exposes the WSGI callable as a module-level variable named ``application``.

For more information on this file, see
https://docs.djangoproject.com/en/4.1/howto/deployment/wsgi/
"""

import os

KEYS_TO_LOAD = [
    'DEBIRDIFY_DJANGO_SECRET',
    'DEBIRDIFY_DEBUG',
    'DEBIRDIFY_ALLOWED_HOSTS',
    'DEBIRDIFY_CALLBACK_URL',
    'DEBIRDIFY_CONSUMER_CREDENTIALS',
    'DEBIRDIFY_ACCESS_CREDENTIALS_COOKIE',
    'DEBIRDIFY_INSTANCE_DB'
]

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "debirdify.settings")

def loading_app(wsgi_environ, start_response):
    global real_app
    for key in KEYS_TO_LOAD:
        try:
            os.environ[key] = wsgi_environ[key]
        except KeyError:
            # The WSGI environment doesn't have the key
            pass
    from django.core.wsgi import get_wsgi_application
    real_app = get_wsgi_application()
    return real_app(wsgi_environ, start_response)

real_app = loading_app

application = lambda env, start: real_app(env, start)

