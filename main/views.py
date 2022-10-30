from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings
import tweepy
from . import extract_mastodon_ids
from tweepy import TweepyException
import re
import datetime
import traceback

def set_cookie(response, key, value, days_expire=7):
    if days_expire is None:
        max_age = 365 * 24 * 60 * 60  # one year
    else:
        max_age = days_expire * 24 * 60 * 60
    expires = datetime.datetime.strftime(
        datetime.datetime.utcnow() + datetime.timedelta(seconds=max_age),
        "%a, %d-%b-%Y %H:%M:%S GMT",
    )
    response.set_cookie(
        key,
        value,
        max_age=max_age,
        expires=expires,
        samesite='Strict',
        secure=True
    )

def mk_oauth1():
    return tweepy.OAuth1UserHandler(
        consumer_key=settings.TWITTER_CONSUMER_CREDENTIALS[0],
        consumer_secret=settings.TWITTER_CONSUMER_CREDENTIALS[1],
        callback=settings.TWITTER_CALLBACK_URL
    )
    
def handle_auth_request(request):
    oauth1_user_handler = mk_oauth1()
    auth_url = oauth1_user_handler.get_authorization_url()
    return render(request, "auth.html", {'auth_url': auth_url})

def make_csv(users):
    return '\n'.join(['Account address,Show boosts'] + ["{},true".format(mid) for u in users for mid in u.mastodon_ids])

def handle_already_authorised(request, access_credentials):
    try:
        client = tweepy.Client(
            consumer_key=settings.TWITTER_CONSUMER_CREDENTIALS[0],
            consumer_secret=settings.TWITTER_CONSUMER_CREDENTIALS[1],
            access_token=access_credentials[0],
            access_token_secret=access_credentials[1]
        )

        me = client.get_me(user_auth=True).data

        if 'screenname' in request.GET:
            screenname = request.GET['screenname']
            if screenname[:1] == '@': screenname = screenname[1:]
            requested_user = client.get_user(username=screenname, user_auth=True).data
            is_me = False
        else:
            screenname=me.username
            requested_user = me
            is_me = True
            
        mastodon_id_users, keyword_users, n_users_searched = extract_mastodon_ids.extract_mastodon_ids(client, requested_user)
        
        context = {
            'mastodon_id_users': mastodon_id_users, 
            'keyword_users': keyword_users, 
            'requested_user': requested_user, 
            'requested_name': screenname, 
            'n_users_searched': n_users_searched,
            'me' : me,
            'is_me': is_me,
            'csv': make_csv(mastodon_id_users)
        }
        response = render(request, "displayresults.html", context)
        set_cookie(response, settings.TWITTER_CREDENTIALS_COOKIE, access_credentials[0] + ':' + access_credentials[1])
        return response
    except tweepy.TooManyRequests:
        response = render(request, "rate.html", {})
        return response
    except TweepyException as e:
        context = {}
        response = render(request, "error.html", context)
        set_cookie(response, settings.TWITTER_CREDENTIALS_COOKIE, access_credentials[0] + ':' + access_credentials[1])
        return response

def try_get_twitter_credentials(request):
    if settings.TWITTER_CREDENTIALS_COOKIE not in request.COOKIES: return None
    xs = request.COOKIES[settings.TWITTER_CREDENTIALS_COOKIE].split(':')
    if len(xs) != 2: return None
    return xs[0].strip(), xs[1].strip()

def index(request):
    # clear the credentials cookie if the users requests it
    if 'clear' in request.GET:
        response = handle_auth_request(request)
        response.delete_cookie(settings.TWITTER_CREDENTIALS_COOKIE)
        return response        

    # try to get credentials from cookie
    twitter_credentials = try_get_twitter_credentials(request)
    if twitter_credentials is not None:
        try:
            return handle_already_authorised(request, twitter_credentials)
        except TweepyException as e:
            pass
    
    # if these are set, the user was redirected back to us after a Twitter OAuth authentication
    if 'oauth_token' in request.GET and 'oauth_verifier' in request.GET:
        request_token = request.GET['oauth_token']
        request_secret = request.GET['oauth_verifier']
        
        oauth1_user_handler = mk_oauth1()
        oauth1_user_handler.request_token = {
          'oauth_token': request_token,
          'oauth_token_secret': request_secret
        }

        try:
            access_token, access_token_secret = oauth1_user_handler.get_access_token(request_secret)
            return handle_already_authorised(request, (access_token, access_token_secret))
        except TweepyException as e:
            return handle_auth_request(request)

    else:
        return handle_auth_request(request)

