from django.shortcuts import render, redirect
from django.http import HttpResponse, JsonResponse
from django.conf import settings
from django.views.decorators.gzip import gzip_page
from django.views.decorators.csrf import csrf_protect
from django.core.exceptions import PermissionDenied
from django.db import connection
import tweepy
from tweepy import TweepyException
import re
import datetime
import traceback
import math
import codecs
import json
from io import TextIOWrapper
from functools import total_ordering

from . import extract_mastodon_ids
from .instance import Instance, get_instance
from .json_path import *
from . import batch as batchtools

class RequestedUserSrc:
    pass    

@total_ordering
class RequestedUserPlainSrc(RequestedUserSrc):
    def __init__(self, original_form, origin, line):
        self.original_form = original_form
        self.origin = origin
        self.line = line
        self.short = f'line {self.line}'
        
    def __eq__(self, other):
        return (isinstance(other, RequestedUserPlainSrc)
            and self.original_form == other.original_form
            and self.origin == other.origin
            and self.line == other.line)
    
    def __lt__(self, other):
        if not isinstance(other, RequestedUserPlainSrc):
            return True
        return (self.line, self.origin, self.original_form) < (other.line, other.origin, other.original_form)
        
    def __str__(self):
        return f'{self.origin}, line {self.line}'

@total_ordering
class RequestedUserJSONSrc(RequestedUserSrc):
    def __init__(self, original_form, origin, path):
        self.origin = origin
        self.path = path
        self.short = str(path)
        self.original_form = original_form

    def __eq__(self, other):
        return (isinstance(other, RequestedUserJSONSrc)
            and self.origin == other.origin
            and self.path == other.path
            and self.original_form == other.original_form)
    
    def __lt__(self, other):
        if isinstance(other, RequestedUserPlainSrc):
            return False
        if not isinstance(other, RequestedUserJSONSrc):
            return True
        return (self.origin, self.path, self.original_form) < (other.origin, other.path, self.original_form)

    def __str__(self):
        return f'{self.origin}, {self.path}'

_twitter_handle_pattern = re.compile('^\s*@?([A-Za-z0-9_]{3,15})\s*$')
    
def parse_twitter_handle(x):
    match = _twitter_handle_pattern.match(x)
    if match is None:
        return None
    else:
        return match[1]

def parse_twitter_handles(origin, handles):
    line = 0
    errors = list()
    results = list()
    for s in handles:
        line += 1
        if not s.strip(): continue
        src = RequestedUserPlainSrc(s, origin, line)
        x = parse_twitter_handle(s)
        if x is None:
            errors.append(extract_mastodon_ids.RequestedUser(src, screenname=s))
        else:
            results.append(extract_mastodon_ids.RequestedUser(src, screenname=x))
    return results, errors
    

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
    print(settings.TWITTER_CALLBACK_URL)
    oauth1 = mk_oauth1()
    auth_url = oauth1.get_authorization_url()
    return render(request, "auth.html", {'auth_url': auth_url})

def make_csv(users):
    return '\n'.join(['Account address,Show boosts'] + ["{},true".format(mid) for u in users for mid in u.mastodon_ids])
    
_full_csv_fields = [
    ('Twitter User ID', 'uid'),
    ('Twitter user name', 'screenname'),
    ('Twitter display name', 'name'),
    ('Source', 'src'),
    ('Is on Fediverse', 'is_on_fediverse')]
    
def make_full_csv(users):
    from io import StringIO
    import csv
    with StringIO() as f:
        w = csv.writer(f)
        w.writerow([x for x, y in _full_csv_fields] + ['Fediverse IDs'])
        for u in users:
            w.writerow([getattr(u, y) for x, y in _full_csv_fields] + [mid for mid in u.mastodon_ids])
        return f.getvalue()

def increase_access_counter():
    pass
#    try:
#        with connection.cursor() as cur:
#            cur.execute("INSERT INTO access_stats (date, count) VALUES (DATE('now'), 1) ON CONFLICT DO UPDATE SET count = count + 1")
#    except Exception as e:
#        print('Failed to increase access counter:', e)

class FileUploadError(Exception):
    pass

@total_ordering
class UploadedFileOrigin:
    def __init__(self, name):
        self.name = name
        self.is_text_area = False
    
    def __str__(self):
        return self.name
    
    def __eq__(self, other):
        return isinstance(other, UploadedFileOrigin) and self.name == other.name
        
    def __hash__(self):
        return hash(self.name)
        
    def __lt__(self, other):
        return isinstance(other, UploadedFileOrigin) and self.name < other.name
        
class TextAreaOrigin:
    def __init__(self):
        self.is_text_area = True

    def __eq__(self, other):
        return isinstance(other, TextAreaOrigin)
    
    def __str__(self):
        return '<text area>'
    
    def __hash__(self):
        return hash("TextAreaOrigin")
        
    def __lt__(self, other):
        return isinstance(other, UploadedFileOrigin)
        
def group(xs, key):
    d = dict()
    for x in xs:
        k = key(x)
        try:
            d[k].append(x)
        except KeyError:
            d[k] = [x]
    return d

_json_archive_types = ['muting', 'blocking', 'following', 'follower']

def parse_archive_json(origin, json_dat):
    results = list()
    
    def add_result(uid, path, typ):
        if not uid or not isinstance(uid, str) or not uid.isnumeric():
            return
        src = RequestedUserJSONSrc(uid, origin, path)
        results.append(extract_mastodon_ids.RequestedUser(src, uid = uid, typ = typ))
    
    def go(x, path):
        if isinstance(x, list):
            i = 0;
            for y in x:
                go(y, JSONArrayItem(path, i))
                i += 1
        elif isinstance(x, dict):
            for typ in _json_archive_types:
                if typ in x and 'accountId' in x[typ]:
                    add_result(x[typ]['accountId'], path, typ)
            for key, val in x.items():
                go(val, JSONDictItem(path, key))

    go(json_dat, JSONRoot())
    return results

_archive_json_pat = re.compile(r'^\s*[A-Za-z0-9_\.]+\s*=\s*(.*)$', re.DOTALL)

def read_archive_json(origin, s):
    try:
        m = _archive_json_pat.match(s)
        if m is not None:
            s = m[1]
        print(s[:200])
        json_dat = json.loads(s)
        results = parse_archive_json(origin, json_dat)
        for u in results:
            print(u)
        return results
    except Exception as e:
        raise e

def read_uploaded_lists(request):
    us = list()
    errors = list()
    for f in request.FILES.getlist('uploaded_list'):
        f_utf8 = TextIOWrapper(f, encoding="utf-8")
        file_src = UploadedFileOrigin(f.name)

        # try to figure out of this is a JSON file from a Twitter archive
        try:
            return read_archive_json(file_src, f_utf8.read()), []
        except:
            pass
    
        # treating it as a plain list file
        line_no = 0
        for l in f_utf8:
            line_no += 1
            l = l.strip()
            if not l: continue
            x = parse_twitter_handle(l)
            src = RequestedUserPlainSrc(l, file_src, line_no)
            if x is None:
                errors.append(extract_mastodon_ids.RequestedUser(src, screenname = l))
            else:
                us.append(extract_mastodon_ids.RequestedUser(src, screenname = x))
    return us, errors
    
class NoSuchUser(Exception):
    pass

def get_job_results(job_secret):
    with connection.cursor() as cur:
        cur.execute('SELECT id, name FROM batch_jobs WHERE text_id=%s', [job_secret])
        row = cur.fetchone()
        if row is None:
            return None
        job_id = row[0]
        job_name = row[1]
        cur.execute('SELECT result FROM batch_job_requests WHERE job_id=%s', [job_id])
        results = extract_mastodon_ids.Results()
        while (row := cur.fetchone()) is not None:
            data = json.loads(row[0])
            u = extract_mastodon_ids.user_result_from_json('Job ' + job_name, data)
            if u is not None:
                results.add(u)
                results.n_users += 1
        return results

def show_error(request, message):
    if 'screenname' in request.POST:
        screenname = request.POST['screenname']
        if screenname[:1] == '@': screenname = screenname[1:]
    else:
        screenname = ''
    context = {
      'error_message': message,
      'requested_name': screenname,
      'pseudolists': extract_mastodon_ids.pseudolists,
      'mastodon_id_users': [],
      'keyword_users': [],
      'n_users_searched': 0,
      'requested_user': None,
      'me': None,
      'is_me': 'screenname' not in request.POST,
      'csv': None
    }
    response = render(request, "displayresults.html", context)
    return response

def handle_already_authorised(request, client, access_credentials):
    screenname = ''
    try:
        me_resp = client.get_me(user_auth=True, user_fields=['name', 'username', 'description', 'entities', 'location', 'pinned_tweet_id', 'public_metrics'], tweet_fields=['entities'], expansions='pinned_tweet_id')
        me = me_resp.data
    
        if 'screenname' in request.POST:
            screenname = request.POST['screenname']
            if screenname[:1] == '@': screenname = screenname[1:]
            requested_user_resp = client.get_user(username=screenname, user_auth=True, user_fields=['name', 'username', 'description', 'entities', 'location', 'pinned_tweet_id', 'public_metrics'],
                tweet_fields=['entities'], expansions='pinned_tweet_id')
            requested_user = requested_user_resp.data
            if requested_user is None:
                raise NoSuchUser
            else:
                is_me = (requested_user.id == me.id)
        else:
            screenname=me.username
            requested_user = me
            requested_user_resp = me_resp
            is_me = True

        def known_host_callback(s):
            try:
                with connection.cursor() as cur:
                    cur.execute('SELECT name FROM instances WHERE name=%s LIMIT 1', [s])
                    row = cur.fetchone()
                    if row is None:
                        try:
                            cur.execute('INSERT INTO unknown_hosts (name) VALUES (%s);', [s])
                        except:
                            pass
                    else:
                        return True
            except Exception as e:
                return False

        broken_mastodon_ids = []
        requested_user_mastodon_ids = []
        requested_user_results = extract_mastodon_ids.Results()
        extract_mastodon_ids.extract_mastodon_ids_from_users(client, None, requested_user_resp, requested_user_results, known_host_callback)
        requested_user_mastodon_ids = requested_user_results.get_results()[0]
        if requested_user_mastodon_ids:
            requested_user_mastodon_ids = requested_user_mastodon_ids[0].mastodon_ids
            for mid in requested_user_mastodon_ids:
                mid.query_exists()
        requested_user_results = extract_mastodon_ids.Results()
        extract_mastodon_ids.extract_mastodon_ids_from_users(client, None, requested_user_resp, requested_user_results, lambda s: True)
        broken_mastodon_ids = list()
        for u in requested_user_results.get_results()[0]:
            for mid in u.mastodon_ids:
                if mid not in requested_user_mastodon_ids:
                    broken_mastodon_ids.append(mid)
                    mid.query_exists()

        lists = None
        results = None
        followed_lists = None
        mid_results = []
        extra_results = []
        all_results = []
        requested_lists = None
        action = None
        n_users = None
        action_taken = True
        uploaded_list_errors = {}
        n_accounts_found = 0

        if 'job_secret' in request.GET:
            action = 'jobresults'
            results = get_job_results(request.GET['job_secret'])
            if results is None:
                return show_error(request, 'This job has been deleted and is no longer available.')            
        elif 'getfollowed' in request.POST:
            action = 'getfollowed'
            results = extract_mastodon_ids.extract_mastodon_ids_from_pseudolist(
                client, requested_user, extract_mastodon_ids.pl_following, known_host_callback = known_host_callback)
        elif 'getfollowers' in request.POST:
            action = 'getfollowers'
            results = extract_mastodon_ids.extract_mastodon_ids_from_pseudolist(
                client, requested_user, extract_mastodon_ids.pl_followers, known_host_callback = known_host_callback)
        elif 'getblocked' in request.POST:
            action = 'getblocked'
            results = extract_mastodon_ids.extract_mastodon_ids_from_pseudolist(
                client, requested_user, extract_mastodon_ids.pl_blocked, known_host_callback = known_host_callback)
        elif 'getmuted' in request.POST:
            action = 'getmuted'
            results = extract_mastodon_ids.extract_mastodon_ids_from_pseudolist(
                client, requested_user, extract_mastodon_ids.pl_muted, known_host_callback = known_host_callback)
        elif 'getlists' in request.POST:
            action = 'getlists'
            lists = extract_mastodon_ids.get_lists(client, requested_user)
            lists_set = set(lists)
            followed_lists = list()
            for l in extract_mastodon_ids.get_lists(client, requested_user, mode='following'):
                if l not in lists_set: followed_lists.append(l)
        elif 'listupload' in request.POST:
            action = 'listupload'
            uploaded_list, uploaded_list_errors = read_uploaded_lists(request)

            list_entry = request.POST.get('list_entry')
            if list_entry is None: list_entry = ''
            try:
                list_entry = read_archive_json(TextAreaOrigin(), list_entry)
                list_entry_errors = []
            except Exception as e:
                list_entry, list_entry_errors = parse_twitter_handles(TextAreaOrigin(), list_entry.splitlines())
            
            uploaded_users = uploaded_list + list_entry
            src = 'Direct Upload'
            
            results, errors = extract_mastodon_ids.extract_mastodon_ids_from_users_raw(client, src, uploaded_users, known_host_callback = known_host_callback)

            uploaded_list_errors = uploaded_list_errors + list_entry_errors + errors
            uploaded_list_errors.sort(key = (lambda u: u.src))
            uploaded_list_errors = group(uploaded_list_errors, key = (lambda x: x.src.origin))

        elif 'getlist' in request.POST:
            action = 'getlist'
            lists = extract_mastodon_ids.get_lists(client, requested_user)
            lists_set = set(lists)
            followed_lists = list()
            for l in extract_mastodon_ids.get_lists(client, requested_user, mode='following'):
                if l not in lists_set: followed_lists.append(l)

            requested_lists = [lst for lst in extract_mastodon_ids.pseudolists + lists + followed_lists if ('list_%s' % lst.id) in request.POST]
            requested_list_ids = [lst.id for lst in requested_lists if not isinstance(lst, extract_mastodon_ids.Pseudolist)]
            
            other_results = dict()
            for pl in extract_mastodon_ids.pseudolists:
                if f'list_{pl.id}' in request.POST:
                    other_results[pl] = extract_mastodon_ids.extract_mastodon_ids_from_pseudolist(
                        client, requested_user, pl, known_host_callback = known_host_callback)
                
            results = extract_mastodon_ids.extract_mastodon_ids_from_lists(client, requested_list_ids, known_host_callback=known_host_callback)
            
            for pl in extract_mastodon_ids.pseudolists:
                if pl in other_results:
                    other_results[pl].merge(results)
                    results = other_results[pl]
        else:
            action_taken = False

        if action_taken:
            increase_access_counter()

        if results is not None:
            mid_results, extra_results, all_results = results.get_results()
            n_users = results.n_users

        n_accounts_found = sum([len(u.mastodon_ids) for u in mid_results])

        mastodon_ids_by_instance = dict()
        for u in mid_results:
            for mid in u.mastodon_ids:
                if mid.host_part in mastodon_ids_by_instance:
                    mastodon_ids_by_instance[mid.host_part].append((u, mid))
                else:
                    mastodon_ids_by_instance[mid.host_part] = [(u, mid)]
        mastodon_ids_by_instance = {get_instance(i): us for i, us in mastodon_ids_by_instance.items()}
        mastodon_ids_by_instance_list = sorted(mastodon_ids_by_instance.items(), key = lambda x: x[0].compare_key(x[1]))
        tmp = 0
        for inst, _ in mastodon_ids_by_instance_list:
            inst.index = tmp
            inst.index_plus_one = tmp + 1
            tmp += 1
                    
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
        
        most_relevant_instances = list()
        for inst, us in mastodon_ids_by_instance.items():
            if inst.users is None or len(us) <= 2: continue
            try:
                inst.score = 1 / (2 - math.log(len(us) / inst.users) * math.log(inst.users)) * 1000
            except:
                continue
            most_relevant_instances.append(inst)
        most_relevant_instances.sort(key = (lambda inst: inst.score), reverse = True)
        n_most_relevant = 20
        most_relevant_instances = most_relevant_instances[:n_most_relevant]
        if len(most_relevant_instances) <= 1: most_relevant_instances = None
        if most_relevant_instances:
            max_score = max([inst.score for inst in most_relevant_instances])
            for inst in most_relevant_instances:
                inst.rel_score = inst.score / max_score * 100
        else:
            max_score = 0.0

        context = {
            'action': action,
            'mastodon_id_users': mid_results,
            'n_accounts_found': n_accounts_found,
            'mastodon_ids_by_instance': mastodon_ids_by_instance_list,
            'service_stats': service_stats,
            'max_score': max_score,
            'most_relevant_instances': most_relevant_instances,
            'requested_user_broken_mastodon_ids': broken_mastodon_ids,
            'requested_user_mastodon_ids': requested_user_mastodon_ids,
            'keyword_users': extra_results,
            'pseudolists': extract_mastodon_ids.pseudolists,
            'requested_user': requested_user, 
            'requested_name': screenname, 
            'requested_lists': requested_lists,
            'n_users_searched': n_users,
            'uploaded_list_errors': sorted(uploaded_list_errors.items(), key = lambda x: x[0]),
            'list_entry': request.POST.get('list_entry') or "",
            'me' : me,
            'is_me': is_me,
            'csv': make_csv(mid_results),
            'full_csv': make_full_csv(all_results),
            'lists': lists,
            'followed_lists': followed_lists
        }
        response = render(request, "displayresults.html", context)
        set_cookie(response, settings.TWITTER_CREDENTIALS_COOKIE, access_credentials[0] + ':' + access_credentials[1])
        return response
    except NoSuchUser:
        context = {
          'error_message': f'The requested Twitter user @{screenname} does not exist.',
          'requested_name': screenname,
          'pseudolists': extract_mastodon_ids.pseudolists,
          'mastodon_id_users': [],
          'keyword_users': [],
          'n_users_searched': 0,
          'requested_user': None,
          'me': None,
          'is_me': False,
          'csv': None
        }
        response = render(request, "displayresults.html", context)
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
          'is_me': 'screenname' not in request.POST,
          'csv': None
        }
        response = render(request, "displayresults.html", context)
        return response
    except (tweepy.BadRequest, tweepy.NotFound) as e:
        print(e)
        if 'screenname' in request.POST:
            screenname = request.POST['screenname']
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
          'is_me': 'screenname' not in request.POST,
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

def profile(request):
    if 'user' not in request.GET or 'host' not in request.GET:
        return render(request, "error2.html", {})
    user = extract_mastodon_ids.MastodonID(request.GET['user'], request.GET['host'])
    url = user.profile_url()
    if url is None:
        url = f'https://{user.host_part}/@{user.user_part}'
    return redirect(url)



def wrap_auth(request, callback):
    def go(access_credentials):
        client = tweepy.Client(
            consumer_key=settings.TWITTER_CONSUMER_CREDENTIALS[0],
            consumer_secret=settings.TWITTER_CONSUMER_CREDENTIALS[1],
            access_token=access_credentials[0],
            access_token_secret=access_credentials[1]
        )
        return callback(request, client, access_credentials)

    # clear the credentials cookie if the users requests it
    if 'clear' in request.GET:
        response = handle_auth_request(request)
        response.delete_cookie(settings.TWITTER_CREDENTIALS_COOKIE)
        return response        

    # try to get credentials from cookie
    twitter_credentials = try_get_twitter_credentials(request)
    if twitter_credentials is not None:
        try:
            return go(twitter_credentials)
        except TweepyException as e:
            pass
    
    # if these are set, the user was redirected back to us after a Twitter OAuth authentication
    if 'oauth_token' in request.GET and 'oauth_verifier' in request.GET:
        request_token = request.GET['oauth_token']
        request_secret = request.GET['oauth_verifier']
        
        oauth1 = mk_oauth1()
        oauth1.request_token = {
          'oauth_token': request_token,
          'oauth_token_secret': request_secret
        }

        try:
            access_token, access_token_secret = oauth1.get_access_token(request_secret)
            return go((access_token, access_token_secret))
        except TweepyException as e:
            print(e)
            return handle_auth_request(request)

    else:
        return handle_auth_request(request)


def batch_aborted_message(job):
    return f'Your batch job ‘{job.name}’ (#{job.id}) was aborted for unknown reasons. Please try again and contact the administrator if this happens a second time.'
    
def batch_still_running_message(job):
    return f'You still have a batch job ‘{job.name}’ (#{job.id}) running. Wait for it to complete or abort it before submitting a new one.'

def batch_launched_message(job):
    return f'Your job ‘{job.name}’ (#{job.id}) was launched successfully. You can monitor the progress by refreshing this page.'

def batch_aborted_by_request_message(job):
    if job is None:
        return 'There is no job to be aborted.'
    else:
        return f'Your job ‘{job.name}’ (#{job.id}) was aborted.'

batch_list_empty_message = 'The list you uploaded contained no valid Twitter user names or IDs, so no job was launched.'

def format_access_credentials(access_credentials):
    return access_credentials[0] + ':' + access_credentials[1]

def ensure_privilege(username, privilege):
    with connection.cursor() as cur:
        cur.execute('SELECT privilege FROM privileges WHERE username=%s AND privilege=%s LIMIT 1', [username.lower(), privilege.lower()])
        if cur.fetchone() is None:
            raise PermissionDenied

def handle_batch(request, client, access_credentials):
    me_resp = client.get_me(user_auth=True)
    me = me_resp.data
    ensure_privilege(me.username, 'batch')    
    job = batchtools.get(me.id)
    
    if 'abort' in request.POST:
        batchtools.delete_all(me.id)
        return render(request, "batch_submit.html", {'me': me, 'message': batch_aborted_by_request_message(job)})
    
    if 'submit' in request.POST:
        if job is not None and not job.aborted and not job.completed:
            return render(request, "batch_progress.html", {'job': job, 'me': me, 'message': batch_still_running_message(job)})
        batchtools.delete_all(me.id)
        name = None
        if 'job_name' in request.POST:
            name = request.POST['job_name']
        if not name: name = '<untitled>'
        requested_users, errors = read_uploaded_lists(request)
        if requested_users:
            job = batchtools.launch(uid = me.id, name = name, requested_users = requested_users, access_credentials = format_access_credentials(access_credentials))
            return redirect('./batch')
            #return render(request, "batch_progress.html", {'job': job, 'me': me, 'message': batch_launched_message(job), 'uploaded_list_errors': errors})
        else:
            return render(request, "batch_submit.html", {'me': me, 'message': batch_list_empty_message, 'uploaded_list_errors': errors})
    
    if job is None:
        return render(request, "batch_submit.html", {'me': me})
    if job.running or job.aborted or job.completed:
        return render(request, "batch_progress.html", {'me': me, 'job': job})
    return render(request, "batch_submit.html", {'me': me})

@gzip_page
@csrf_protect
def batch(request):
    return wrap_auth(request, handle_batch)
    
def batch_progress(request):
    if 'job_secret' not in request.GET:
        raise PermissionDenied
    with connection.cursor() as cur:
        cur.execute('SELECT progress, time_completed FROM batch_jobs WHERE text_id=%s LIMIT 1', [request.GET['job_secret']])
        progress, time_completed = cur.fetchone()
        if time_completed is not None:
            time_completed = time_completed.isoformat()
        return JsonResponse({'progress': progress, 'completed': time_completed})

@gzip_page
@csrf_protect
def index(request):
    return wrap_auth(request, handle_already_authorised)


