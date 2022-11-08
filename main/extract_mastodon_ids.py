import re
from itertools import islice
from functools import partial
import tweepy
import requests

# Max pages of lists to query (1 page is roughly 100 lists)
max_lists_pages = 5

# Max pages of list members to query (1 page is roughly 100 members)
max_list_member_pages = 200

class RequestedUser:
    def __init__(self, name, src):
        self.name = name
        self.src = src
    
    def __eq__(self, other):
        return instanceof(other, RequestedUser) and self.name == other.name and self.src == other.src

    def __str__(self):
        return f'{self.name} ({self.src})'

class List:
    def __init__(self, id, name, member_count, origin='owned'):
        self.id = id
        self.name = name
        self.member_count = member_count
        self.origin = origin

    def __eq__(self, other):
        return self.id == other.id

    def __hash__(self):
        return hash(self.id)

    def __str__(self):
        return self.name

class Pseudolist(List):
    def __init__(self, id, name, api_call, private = False, max_results = 1000, page_limit = 15):
        super(Pseudolist, self).__init__(id, name, None)
        self.private = private
        self.max_results = max_results
        self.page_limit = page_limit
        self.api_call = api_call
       

pl_following = Pseudolist('following', 'Followed accounts', 'get_users_following')
pl_followers = Pseudolist('followers', 'Followers', 'get_users_followers')
pl_blocked = Pseudolist('blocked', 'Blocked accounts', 'get_blocked', private = True)
pl_muted = Pseudolist('muted', 'Muted accounts', 'get_muted', private = True)

pseudolists = [pl_following, pl_followers, pl_blocked, pl_muted]

_host_heuristic_keywords = ['social', 'masto', 'mastodon']

_forbidden_hosts = {
  'tiktok.com', 'youtube.com', 'medium.com', 'skeb.jp', 'pronouns.page', 'foundation.app', 'gamejolt.com', 'traewelling.de', 'observablehq.com', 
  'gmail.com', 'hotmail.com', 'manylink.co', 'withkoji.com', 'twitter.com', 'nomadlist.com', 'figma.com', 'peakd.com', 'jabber.ccc.de',
  'yahoo.com', 'aol.com', 'vice.com', 'wsj.com', 'theguardian.com', 'cbsnews.com', 'cnn.com', 'welt.de', 'nytimes.com', 'gmx.de', 'web.de',
  'posteo.de', 'arcor.de', 'bell.net'}

# Matches anything of the form @foo@bar.bla or foo@bar.social or foo@social.bar or foo@barmastodonbla
# We do not match everything of the form foo@bar or foo@bar.bla to avoid false positives like email addresses
_id_pattern1 = re.compile(r'(@|🐘|Mastodon:?)?\s*?([\w\-\.]+@[\w\-\.]+\.[\w\-\.]+)', re.IGNORECASE)
_id_pattern2 = re.compile(r'\b((http://|https://)?([\w\-\.]+\.[\w\-\.]+)/(web/)?@([\w\-\.]+))/?\b', re.IGNORECASE)
_url_pattern = re.compile(r'^(http://|https://)([\w\-\.]+\.[\w\-\.]+)/(web/)?@([\w\-\.]+)/?$', re.IGNORECASE)

def is_forbidden_host(h):
    xs = h.lower().split('.')
    for i in range(0, len(xs)):
        if '.'.join(xs[i:]) in _forbidden_hosts: return True
    return False

def matches_host_heuristic(s):
    xs = s.lower().split('.')
    for kw in _host_heuristic_keywords:
        if kw in xs: return True
    return None


class InstanceValidator:
    def __init__(self, known_host_callback=None, mode='strict'):
        if known_host_callback is None:
            self.known_host_callback = (lambda x: False)
        else:
            self.known_host_callback = known_host_callback
        self.mode = mode

    def validate_host(self, h):
        s = h.lower()
        if is_forbidden_host(s): return False
        
        if self.known_host_callback is None:
            callback_result = None
        else:
            callback_result = self.known_host_callback(s)

        if self.mode == 'lax':
            return True
        b = matches_host_heuristic(s)
        if b is not None:
            return b

        if callback_result:
            return True
        return False
    
    # for modes see "is_fediverse_host"
    def make_mastodon_id(self, u, h, original = None):
        if self.validate_host(h):
            return MastodonID(u, h, original = original)
        else:
            return None


# Matches some key words that might occur in bios
_keyword_pattern = re.compile(r'.*(mastodon|toot|tröt|fedi).*', re.IGNORECASE)

class MastodonID:
    def __init__(self, user_part, host_part, original = None):
        self.user_part = user_part.lower()
        self.host_part = host_part.lower()
        self.original = original
        self.exists = None

    def __str__(self):
        return '{}@{}'.format(self.user_part, self.host_part)
        
    def url(self):
        return 'https://{}/@{}'.format(self.host_part, self.user_part)
        
    def __eq__(self, other):
        return self.user_part == other.user_part and self.host_part == other.host_part
        
    def __hash__(self):
        return hash((self.user_part, self.host_part))
        
    def query_exists(self):
        url = f'https://{self.host_part}/.well-known/webfinger?resource=acct:{self}'
        try:
            resp = requests.head(url, timeout=2, allow_redirects=True)
            if resp.status_code == 404:
                self.exists = False
            elif resp.status_code == 403:
                self.exists = 'forbidden'
            elif resp.status_code == 200:
                self.exists = True
            else:
                self.exists = None
        except:
            self.exists = 'error'
        return self.exists
        

class UserResult:
    def __init__(self, uid, name, screenname, bio, mastodon_ids, extras):
        self.uid = uid
        self.name = name
        self.screenname = screenname
        self.bio = bio
        self.mastodon_ids = mastodon_ids
        self.extras = extras
        
    def merge(self, r):
        if r.uid != self.uid: return
        if r.mastodon_ids is not None:
            for mid in r.mastodon_ids:
                if mid not in self.mastodon_ids:
                   self.mastodon_ids.append(mid)
            self.mastodon_ids.sort(key=str)
        if r.extras is not None:
            for extra in r.extras:
               if extra not in self.extras:
                   self.extras.append(extra)
            self.extras.sort()

def extract_urls_from_user(u, known_host_callback = None):
    if u is None or u.entities is None: return []
    results = list()
    def aux(urls):
        for url in urls:
            if 'expanded_url' in url:
                results.append(url['expanded_url'])
            elif 'url' in url:
                results.append(url['url'])
    if ('url' in u.entities) and ('urls' in u.entities['url']):
        aux(u.entities['url']['urls'])
    if ('description' in u.entities) and ('urls' in u.entities['description']):
        aux(u.entities['description']['urls'])
    if ('location' in u.entities) and ('urls' in u.entities['location']):
        aux(u.entities['location']['urls'])
    return results

def extract_urls_from_tweet(t):
    if t is None or t.entities is None or 'urls' not in t.entities: return []
    return [x['expanded_url'] for x in t.entities['urls'] if 'expanded_url' in x]

def get_lists(client, requested_user, mode = 'normal'):
    next_token = None
    results = list()
    page = 1
    origin = 'owned'
    if mode == 'following': origin = 'following'
    while page <= max_lists_pages:
        page += 1
        try:
            if mode == 'following':
                resp = client.get_followed_lists(requested_user.id, user_auth=True, user_fields='id', list_fields=['member_count'], pagination_token=next_token)
            else:
                resp = client.get_owned_lists(requested_user.id, user_auth=True, user_fields='id', list_fields=['member_count'], pagination_token=next_token)
        except tweepy.TooManyRequests as e:
            if page == 1: raise e
            break
        lists = resp.data or []
        for lst in lists:
            results.append(List(lst.id, lst.name, lst.member_count, origin = origin))
        try:
          next_token = resp.meta['next_token']
        except:
          next_token = None
        if next_token is None: break
    return results
    
class Results:
    def __init__(self):
        self.results = dict()
        self.n_users = 0
        
    def add(self, r):
        if r.uid in self.results:
            self.results[r.uid].merge(r)
        else:
            self.results[r.uid] = r
            
    def merge(self, rs):
        for r in rs.results.values():
            self.add(r)
        self.n_users += rs.n_users

    def get_results(self):
        mid_results = [r for r in self.results.values() if r.mastodon_ids]
        mid_results.sort(key=(lambda u: u.screenname))
        extra_results = [r for r in self.results.values() if not r.mastodon_ids and r.extras]
        extra_results.sort(key=(lambda u: u.screenname))
        return mid_results, extra_results

def is_mastodon_id_char(s):
    return s.isalnum() or s == '_'
    
# client: a tweepy.Client object
# requested_user: a tweepy.User object
# returns:
#   a tuple consisting of two lists UserResult objects.
#   the first component contains a list of users that seem to have a Mastodon ID in their name or bio
#   the second component contains a list of users that have some keyword in their bio that looks Mastodon-related
def extract_mastodon_ids_from_users(client, resp, results, known_host_callback = None):
    if resp.data is None: return
    lax_validator = InstanceValidator(known_host_callback=known_host_callback, mode = 'lax')
    strict_validator = InstanceValidator(known_host_callback=known_host_callback, mode = 'strict')
    
    # Takes a Mastodon ID in the format @foo@bar.tld or foo@bar.tld and returns
    # a MastodonID object. If the string starts with an @, lax host validation is performed
    def parse_mastodon_id(s, certain = False):
        validator = strict_validator
        if not is_mastodon_id_char(s[-1:]): s = s[:-1] # remove possible trailing punctuation
        if certain: validator = lax_validator
        tmp = s.split('@')
        if len(tmp) != 2:
            return None
        return validator.make_mastodon_id(tmp[0], tmp[1], original = s)

    users = resp.data
    if 'id' in users: users = [users]    
    if not users: return
    pinned_tweets = resp.includes.get('tweets') or []
    if pinned_tweets is None: pinned_tweets = []
    pinned_tweets = {t.id: t for t in pinned_tweets}
    
    for u in users:
        if u is None: continue
        uid = u.id
        name = u.name
        location = u.location
        screenname = u.username
        bio = u.description
        if u.pinned_tweet_id is not None:
            pinned_tweet = pinned_tweets.get(u.pinned_tweet_id)
            pinned_tweet_text = pinned_tweet.text
        else:
            pinned_tweet = None
            pinnet_tweet_text = ""
            
        extras = None
        # Parse Mastodon IDs of the form @foo@bar.tld or foo@bar.tld
        # Strict host validation is performed in the second form (i.e. must not be forbidden,
        # must pass heuristic or be a known host)
        mastodon_ids = set()
        
        for text in [name, location, bio, pinned_tweet_text]:
            if text is None: continue
            for prefix, s in _id_pattern1.findall(text):
                certain = False
                if prefix: certain = True
                mid = parse_mastodon_id(s, certain = certain)
                if mid is not None: mastodon_ids.add(mid)

        # Now we check for URLs of the form bar.tld/@foo or bar.tld/web/@foo
        # We use lax validation, i.e. unless the host is explicitly in the forbidden
        # list we assume it is genuine.

        # Check URLs in entities of bio, website, pinned tweet for 
        for url in extract_urls_from_user(u) + extract_urls_from_tweet(pinned_tweet):
            for _, h_str, _, u_str in _url_pattern.findall(url):
                mid = strict_validator.make_mastodon_id(u_str, h_str, original = url)
                if mid is not None: mastodon_ids.add(mid)

        # Check for URLs in name and location
        for s in (name, location):
            if s is None: continue
            for entire_match, _, h_str, _, u_str in _id_pattern2.findall(s):
                mid = strict_validator.make_mastodon_id(u_str, h_str, original = entire_match)
                if mid is not None: mastodon_ids.add(mid)
        
        # Check for URLs in screenname, bio pinned_tweet
        texts = [screenname, bio]
        if pinned_tweet is not None: texts.append(pinned_tweet.text)
        for text in texts:
            for entire_match, _, h_str, _, u_str in _id_pattern2.findall(text):
                mid = strict_validator.make_mastodon_id(u_str, h_str, original = entire_match)
                if mid is not None: mastodon_ids.add(mid)
                
        mastodon_ids = list(mastodon_ids)
        mastodon_ids.sort(key=(lambda mid: str(mid)))
        
        if not mastodon_ids:
          extras = list()
          for d in u.description.splitlines():
              if _keyword_pattern.match(d): extras.append(d)
          if not extras: extras = None
        
        results.add(UserResult(uid, name, screenname, bio, mastodon_ids, extras))

def chunks_of(seq, size):
    return iter(partial(lambda it: tuple(islice(it, size)), iter(seq)), ())

def extract_mastodon_ids_from_users_raw(client, users, known_host_callback = None):
    results = Results()
    errors = list()
    if not users: return results, errors
    
    for us in chunks_of(users, 100):
        resp = client.get_users(
                usernames = ','.join([u.name for u in us]), 
                user_auth=True, 
                user_fields=['name', 'username', 'description', 'entities', 'location', 'pinned_tweet_id'],
                tweet_fields=['entities'], 
                expansions='pinned_tweet_id')
        if resp.data is None: continue
        n = len(us)
        i = 0
        
        us_dict = dict()
        for u in us:
            try:
                s = u.name.lower()
                us_dict[s].append(u)
            except KeyError:
                us_dict[s] = [u]

        for u in resp.data:
            if u is not None:
                results.n_users += 1
                try:
                    del us_dict[u.username.lower()]
                except KeyError:
                    pass
        for errs in us_dict.values():
            for err in errs:
                errors.append(err)
        extract_mastodon_ids_from_users(client, resp, results, known_host_callback=known_host_callback)
    return results, errors

def extract_mastodon_ids_from_pseudolist(client, requested_user, pl, known_host_callback = None):
    next_token = None
    pages = 1
    results = Results()

    while pages <= pl.page_limit:
        api_call = getattr(client, pl.api_call)
        try:
            if pl.private:
                resp = api_call(
                    max_results=pl.max_results, 
                    user_auth=True, 
                    user_fields=['name', 'username', 'description', 'entities', 'location', 'pinned_tweet_id'],
                    tweet_fields=['entities'], 
                    expansions='pinned_tweet_id', 
                    pagination_token=next_token)
            else:
                resp = api_call(
                    requested_user.id, 
                    max_results=pl.max_results, 
                    user_auth=True, 
                    user_fields=['name', 'username', 'description', 'entities', 'location', 'pinned_tweet_id'],
                    tweet_fields=['entities'], 
                    expansions='pinned_tweet_id', 
                    pagination_token=next_token)
        except tweepy.TooManyRequests as e:
            if pages == 1: raise e
            break

        try:
          next_token = resp.meta['next_token']
        except:
          next_token = None

        users = resp.data
        if users is None: users = []
        extract_mastodon_ids_from_users(client, resp, results, known_host_callback=known_host_callback)
        pages = pages + 1
        results.n_users += len(users)
       
        if next_token is None:
            break

    return results
    
def extract_mastodon_ids_from_lists(client, requested_list_ids, known_host_callback=None):
    next_token = None
    pages = 1
    results = Results()

    for list_id in requested_list_ids:
        while pages <= max_list_member_pages:
            try:
                resp = client.get_list_members(list_id,
                        user_auth=True, 
                        user_fields=['name', 'username', 'description', 'entities', 'location', 'pinned_tweet_id'],
                        tweet_fields=['entities'], 
                        expansions='pinned_tweet_id', 
                        pagination_token=next_token)
            except tweepy.TooManyRequests as e:
                if pages == 1: raise e
                break

            try:
              next_token = resp.meta['next_token']
            except:
              next_token = None

            users = resp.data
            if users is None: users = []
            extract_mastodon_ids_from_users(client, resp, results, known_host_callback=known_host_callback)
            pages = pages + 1
            results.n_users += len(users)
           
            if next_token is None:
                break

    return results

