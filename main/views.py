from django.shortcuts import render
from django.http import HttpResponse
from django.conf import settings
from django.views.decorators.gzip import gzip_page
import tweepy
import sqlite3
from . import extract_mastodon_ids
from tweepy import TweepyException
import re
import datetime
import traceback

logos = {
    'aardwolf': 'aardwolf.png', 'bonfire': 'bonfire.png', 'bookwyrm': 'bookwyrm.png', 'calckey': 'calckey.png', 'castopod': 'castopod.svg',
    'diaspora': 'diaspora.svg', 'dokieli': 'dokieli.png', 'drupal': 'drupal.svg', 'epicyon': 'epicyon.png', 'forgefriends': 'forgefriends.svg',
    'friendica': 'friendica.svg', 'funkwhale': 'funkwhale.svg', 'gancio': 'gancio.png', 'gnusocial': 'gnusocial.svg', 
    'gotosocial': 'gotosocial.png', 'guppe': 'guppe.png', 'kbin': 'kbin.png', 'ktistec': 'ktistec.png', 'lemmy': 'lemmy.svg', 
    'mastodon': 'mastodon.svg', 'minipub': 'minipub.svg', 'misskey': 'misskey.png', 'misty': 'misty.png', 'mobilizon': 'mobilizon.svg',
    'nextcloud': 'nextcloud.png', 'ocelot': 'ocelot.svg', 'osada': 'osada.png', 'owncast': 'owncast.svg', 'peertube': 'peertube.svg', 
    'pixelfed': 'pixelfed.svg', 'pleroma': 'pleroma.svg', 'plume': 'plume.svg', 'readas': 'readas.svg', 'redmatrix': 'redmatrix.png', 
    'roadhouse': 'roadhouse.png', 'socialhome': 'socialhome.svg', 'wordpress': 'wordpress.svg', 'writefreely': 'writefreely.svg', 
    'zap': 'zap.png'}


def mk_int(x):
    if x is None: return None
    try:
        return int(x)
    except:
        return None

def mk_bool(x):
    if x is None: return None
    if isinstance(x, bool): return x
    if x in ('1', 'true', 'True'): return True
    if x in ('0', 'false', 'False'): return False
    return None

class Instance:
    def __init__(self, host, software, software_version, registrations_open, users, active_month, active_halfyear, local_posts, last_update, uptime, dead, up):
        host = host.lower()
        self.host = host
        if software is None:
            self.software = None
        else:
            self.software = software.lower()
        self.software_version = software_version
        self.registrations_open = mk_bool(registrations_open)
        self.users = mk_int(users)
        self.active_month = mk_int(active_month)
        self.active_halfyear = mk_int(active_halfyear)
        self.local_posts = mk_int(local_posts)
        self.dead = dead
        self.up = up
        self.uptime = None
        if uptime is not None:
            try:
                if uptime == 1.0:
                    self.uptime = '100 %'
                elif uptime >= 0.9998:
                    self.uptime = '%.3f %%' % (float(uptime)*100)
                elif uptime >= 0.998:
                    self.uptime = '%.2f %%' % (float(uptime)*100)
                elif uptime >= 0.98:
                    self.uptime = '%.1f %%' % (float(uptime)*100)
                else:
                    self.uptime = '%.0f %%' % (float(uptime)*100)
            except:
                pass
        self.icon = logos.get(self.software)

        stats = None
        if self.users is not None:
            stats = f'users: {self.users}'
            tmp = list()
            # uptime is broken in instances.social
#            for x, y in [('active_month', 'last month'), ('active_halfyear', 'last 6 months'), ('uptime', 'uptime')]:
            for x, y in [('active_month', 'last month'), ('active_halfyear', 'last 6 months')]:
                z = getattr(self, x)
                if z is None: continue
                tmp.append(f'{y}: {z}')
            if tmp: stats = stats + ' (' + '; '.join(tmp) + ')'
        self.stats = stats
            
        try:
            self.last_update = datetime.datetime.fromisoformat(last_update)
            self.last_update_pretty = self.last_update.strftime('%-d %B %Y, %H:%M')
        except:
            self.last_update = None
            
    def compare_key(self, us):
        if self.software == 'mastodon':
            x = ''
        elif self.software is None:
            x = '~'
        else:
            x = self.software
        if self.dead == False:
            dead = 0
        else:
            dead = 1
        return (x, dead, -len(us))
    
    def __str__(self):
        return self.host
        
    def __hash__(self):
        return hash(self.host)
        
    def __eq__(self, other):
        return self.host == other.host

def naked_instance(name):
    return Instance(name.lower(), None, None, None, None, None, None, None, None, None, None, None)

def get_instance(conn, name):
    if conn is None: return naked_instance(name)
    try:
        cur = conn.cursor()
        cur.execute('SELECT name, software, software_version, registrations_open, users, active_month, active_halfyear, local_posts, last_update, uptime, dead, up FROM instances WHERE name=? LIMIT 1', (name.lower(),))
        row = cur.fetchone()
        if row is None: return naked_instance(name)
        i = Instance(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10], row[11])
        return i
    except Exception as e:
        print(e)
        return naked_instance(name)

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
        secure=True,
        httponly=True
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
    screenname = ''
    try:
        client = tweepy.Client(
            consumer_key=settings.TWITTER_CONSUMER_CREDENTIALS[0],
            consumer_secret=settings.TWITTER_CONSUMER_CREDENTIALS[1],
            access_token=access_credentials[0],
            access_token_secret=access_credentials[1]
        )

        me_resp = client.get_me(user_auth=True, user_fields=['name', 'username', 'description', 'entities', 'location', 'pinned_tweet_id', 'public_metrics'],
                tweet_fields=['entities'], expansions='pinned_tweet_id')
        me = me_resp.data

        if 'screenname' in request.GET:
            screenname = request.GET['screenname']
            if screenname[:1] == '@': screenname = screenname[1:]
            requested_user_resp = client.get_user(username=screenname, user_auth=True, user_fields=['name', 'username', 'description', 'entities', 'location', 'pinned_tweet_id', 'public_metrics'],
                tweet_fields=['entities'], expansions='pinned_tweet_id')
            requested_user = requested_user_resp.data
            is_me = (requested_user.id == me.id)
        else:
            screenname=me.username
            requested_user = me
            requested_user_resp = me_resp
            is_me = True

        if settings.INSTANCE_DB is not None:
            try:
                instance_db = sqlite3.connect(settings.INSTANCE_DB)
                cursor = instance_db.cursor()
            except Exception as e:
                instance_db = None 
                cursor = None
        else:
            instance_db = None
            cursor = None

        def known_host_callback(s):
            if cursor is None:
                return False
            try:
                row = cursor.execute('SELECT name FROM instances WHERE name=?', (s,)).fetchone()
                if row is None:
                    try:
                        instance_db.execute('INSERT INTO unknown_hosts (name) VALUES (?);', (s,))
                        instance_db.commit()
                    except:
                        pass
                else:
                    return True
            except:
                return False
                
        broken_mastodon_ids = []
        requested_user_mastodon_ids = []
        requested_user_results = extract_mastodon_ids.Results()
        extract_mastodon_ids.extract_mastodon_ids_from_users(client, requested_user_resp, requested_user_results, known_host_callback)
        requested_user_mastodon_ids = requested_user_results.get_results()[0]
        if requested_user_mastodon_ids:
            requested_user_mastodon_ids = requested_user_mastodon_ids[0].mastodon_ids
            for mid in requested_user_mastodon_ids:
                mid.query_exists()
        requested_user_results = extract_mastodon_ids.Results()
        extract_mastodon_ids.extract_mastodon_ids_from_users(client, requested_user_resp, requested_user_results, lambda s: True)
        broken_mastodon_ids = list()
        for u in requested_user_results.get_results()[0]:
            for mid in u.mastodon_ids:
                if mid not in requested_user_mastodon_ids:
                    broken_mastodon_ids.append(mid)
                    mid.query_exists()

        lists = None
        results = None
        mid_results = []
        extra_results = []
        requested_lists = None
        action = None
        n_users = None

        if 'getfollowed' in request.GET:
            action = 'getfollowed'
            results = extract_mastodon_ids.extract_mastodon_ids_from_pseudolist(
                client, requested_user, extract_mastodon_ids.pl_following, known_host_callback = known_host_callback)
        elif 'getfollowers' in request.GET:
            action = 'getfollowers'
            results = extract_mastodon_ids.extract_mastodon_ids_from_pseudolist(
                client, requested_user, extract_mastodon_ids.pl_followers, known_host_callback = known_host_callback)
        elif 'getblocked' in request.GET:
            action = 'getblocked'
            results = extract_mastodon_ids.extract_mastodon_ids_from_pseudolist(
                client, requested_user, extract_mastodon_ids.pl_blocked, known_host_callback = known_host_callback)
        elif 'getmuted' in request.GET:
            action = 'getmuted'
            results = extract_mastodon_ids.extract_mastodon_ids_from_pseudolist(
                client, requested_user, extract_mastodon_ids.pl_muted, known_host_callback = known_host_callback)
        elif 'getlists' in request.GET:
            action = 'getlists'
            lists = extract_mastodon_ids.get_lists(client, requested_user)
        elif 'getlist' in request.GET:
            action = 'getlist'
            lists = extract_mastodon_ids.get_lists(client, requested_user)
            requested_lists = [lst for lst in extract_mastodon_ids.pseudolists + lists if ('list_%s' % lst.id) in request.GET]
            requested_list_ids = [lst.id for lst in requested_lists if not isinstance(lst, extract_mastodon_ids.Pseudolist)]
            
            other_results = dict()
            for pl in extract_mastodon_ids.pseudolists:
                if f'list_{pl.id}' in request.GET:
                    other_results[pl] = extract_mastodon_ids.extract_mastodon_ids_from_pseudolist(
                        client, requested_user, pl, known_host_callback = known_host_callback)
                
            results = extract_mastodon_ids.extract_mastodon_ids_from_lists(client, requested_list_ids, known_host_callback=known_host_callback)
            
            for pl in extract_mastodon_ids.pseudolists:
                if pl in other_results:
                    other_results[pl].merge(results)
                    results = other_results[pl]
                
        if results is not None:
            mid_results, extra_results = results.get_results()
            n_users = results.n_users

        mastodon_ids_by_instance = dict()
        for u in mid_results:
            for mid in u.mastodon_ids:
                if mid.host_part in mastodon_ids_by_instance:
                    mastodon_ids_by_instance[mid.host_part].append((u, mid))
                else:
                    mastodon_ids_by_instance[mid.host_part] = [(u, mid)]
        mastodon_ids_by_instance = {get_instance(instance_db, i): us for i, us in mastodon_ids_by_instance.items()}
                    
        service_stats = dict()
        for inst, us in mastodon_ids_by_instance.items():
            if inst.software is None:
                software = 'Unknown'
            else:
                software = inst.software.title()
            if software in service_stats:
                service_stats[software] += len(us)
            else:
                service_stats[software] = len(us)
        def service_key(x):
            if x[0] == 'Unknown':
                return 1
            else:
                return -int(x[1])
        service_stats = sorted(service_stats.items(), key = service_key)
        
        try:
            if instance_db is not None: instance_db.close()
        except:
            pass
                    
        context = {
            'action': action,
            'mastodon_id_users': mid_results,
            'mastodon_ids_by_instance': sorted(mastodon_ids_by_instance.items(), key = lambda x: x[0].compare_key(x[1])),
            'service_stats': service_stats,
            'requested_user_broken_mastodon_ids': broken_mastodon_ids,
            'requested_user_mastodon_ids': requested_user_mastodon_ids,
            'keyword_users': extra_results,
            'pseudolists': extract_mastodon_ids.pseudolists,
            'requested_user': requested_user, 
            'requested_name': screenname, 
            'requested_lists': requested_lists,
            'n_users_searched': n_users,
            'me' : me,
            'is_me': is_me,
            'csv': make_csv(mid_results),
            'lists': lists
        }
        response = render(request, "displayresults.html", context)
        set_cookie(response, settings.TWITTER_CREDENTIALS_COOKIE, access_credentials[0] + ':' + access_credentials[1])
        return response
    except tweepy.TooManyRequests:
        context = {
          'error_message': 'You made too many requests too quickly. Please slow down a bit. This is not us being petty; Twitter enforces per-user rate limiting. This can happen especially if you repeatedly search through hundreds or thousands of accounts.',
          'requested_name': screenname,
          'pseudolists': extract_mastodon_ids.pseudolists,
          'mastodon_id_users': [],
          'keyword_users': [],
          'n_users_searched': 0,
          'requested_user': None,
          'me': None,
          'is_me': 'screenname' not in request.GET,
          'csv': None
        }
        response = render(request, "displayresults.html", context)
        return response
    except (tweepy.BadRequest, tweepy.NotFound) as e:
        if 'screenname' in request.GET:
            screenname = request.GET['screenname']
            if screenname[:1] == '@': screenname = screenname[1:]
        else:
            screenname = ''
        context = {
          'error_message': 'The Twitter API rejected our request. Are you sure what you entered is a valid Twitter handle? (e.g. @pruvisto)',
          'requested_name': screenname,
          'pseudolists': extract_mastodon_ids.pseudolists,
          'mastodon_id_users': [],
          'keyword_users': [],
          'n_users_searched': 0,
          'requested_user': None,
          'me': None,
          'is_me': 'screenname' not in request.GET,
          'csv': None
        }
        response = render(request, "displayresults.html", context)
        return response
    except ConnectionError as e:
        context = {}
        response = render(request, "error.html", context)
        set_cookie(response, settings.TWITTER_CREDENTIALS_COOKIE, access_credentials[0] + ':' + access_credentials[1])
        return response        
    except TweepyException as e:
        print(e)
        traceback.print_exc()
        context = {}
        response = render(request, "error.html", context)
        set_cookie(response, settings.TWITTER_CREDENTIALS_COOKIE, access_credentials[0] + ':' + access_credentials[1])
        return response

def try_get_twitter_credentials(request):
    if settings.TWITTER_CREDENTIALS_COOKIE not in request.COOKIES: return None
    xs = request.COOKIES[settings.TWITTER_CREDENTIALS_COOKIE].split(':')
    if len(xs) != 2: return None
    return xs[0].strip(), xs[1].strip()

@gzip_page
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
            print(e)
            return handle_auth_request(request)

    else:
        return handle_auth_request(request)

