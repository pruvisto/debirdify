import re
import tweepy

# Max pages of followees to query (1 page is roughly 1000 followees)
max_pages = 5

_forbidden_hosts = {'tiktok.com', 'youtube.com', 'medium.com', 'skeb.jp', 'pronouns.page', 'foundation.app', 'gamejolt.com', 'traewelling.de'}

# Matches anything of the form @foo@bar.bla or foo@bar.social or foo@social.bar or foo@barmastodonbla
# We do not match everything of the form foo@bar or foo@bar.bla to avoid false positives like email addresses
_id_pattern1 = re.compile(r'(@[\w\-\.]+@[\w\-\.]+\.[\w\-\.]+|[\w\-\.]+@[\w\-\.]+\.social|[\w\-\.]+@social\.[\w\-\.]+|[\w\-\.]+@[\w\-\.]*mastodon[\w\-\.]+)', re.IGNORECASE)
_id_pattern2 = re.compile(r'\b(http://|https://)?([\w\-\.]+\.[\w\-\.]+)/(web/)?@([\w\-\.]+)/?\b', re.IGNORECASE)
_url_pattern = re.compile(r'^(http://|https://)([\w\-\.]+\.[\w\-\.]+)/(web/)?@([\w\-\.]+)/?$', re.IGNORECASE)

def is_forbidden_host(h):
    xs = h.lower().split('.')
    for i in range(0, len(xs)):
        if '.'.join(xs[i:]) in _forbidden_hosts: return True
    return False

# Matches some key words that might occur in bios
_keyword_pattern = re.compile(r'.*(mastodon|toot|tröt|fedi).*', re.IGNORECASE)

class MastodonID:
    def __init__(self, user_part, host_part):
        self.user_part = user_part.lower()
        self.host_part = host_part.lower()

    def __str__(self):
        return '{}@{}'.format(self.user_part, self.host_part)
        
    def url(self):
        return 'https://{}/@{}'.format(self.host_part, self.user_part)
        
    def __eq__(self, other):
        return self.user_part == other.user_part and self.host_part == other.host_part
        
    def __hash__(self):
        return hash((self.user_part, self.host_part))
        
def parse_mastodon_id(s):
    if s[:1] == '@':
        s = s[1:]
    tmp = s.split('@')
    if len(tmp) != 2:
        return None
    return MastodonID(tmp[0], tmp[1])       

class UserResult:
    def __init__(self, uid, name, screenname, bio, mastodon_ids, extras):
        self.uid = uid
        self.name = name
        self.screenname = screenname
        self.bio = bio
        self.mastodon_ids = mastodon_ids
        self.extras = extras

def extract_urls_from_user(u):
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

def make_mastodon_id(u, h):
    if is_forbidden_host(h): return None
    return MastodonID(u, h)

# client: a tweepy.Client object
# requested_user: a tweepy.User object
# returns:
#   a tuple consisting of two lists UserResult objects.
#   the first component contains a list of users that seem to have a Mastodon ID in their name or bio
#   the second component contains a list of users that have some keyword in their bio that looks Mastodon-related
def extract_mastodon_ids(client, requested_user):
    results1 = list()
    results2 = list()
    if requested_user is None: return results1, results2
    
    next_token = None
    pages = 1
    n_users = 0
    tweet_rate_limit_hit = False
        
    while pages <= max_pages:
        resp = client.get_users_following(requested_user.id, max_results=1000, user_auth=True, user_fields=['name', 'username', 'description', 'entities', 'location', 'pinned_tweet_id'], tweet_fields=['entities'], expansions='pinned_tweet_id', pagination_token=next_token)

        try:
          next_token = resp.meta['next_token']
        except:
          next_token = None
        users = resp.data
        pinned_tweets = resp.includes.get('tweets') or []
        pinned_tweets = {t.id: t for t in pinned_tweets}
        pages = pages + 1
        n_users += len(users)
        
        for u in users:
            uid = u.id
            name = u.name
            location = u.location
            screenname = u.username
            bio = u.description
            if u.pinned_tweet_id is not None:
                pinned_tweet = pinned_tweets.get(u.pinned_tweet_id)
            else:
                pinned_tweet = None
                
            extras = None
            mastodon_ids = {mid for s in _id_pattern1.findall(name) + _id_pattern1.findall(bio)
                                if (mid := parse_mastodon_id(s)) is not None}
            for url in extract_urls_from_user(u) + extract_urls_from_tweet(pinned_tweet):
                for _, h_str, _, u_str in _url_pattern.findall(url):
                    mid = make_mastodon_id(u_str, h_str)
                    if mid is not None: mastodon_ids.add(mid)
            for s in (name, location):
                if s is None: continue
                for _, h_str, _, u_str in _id_pattern2.findall(s):
                    mid = make_mastodon_id(u_str, h_str)
                    if mid is not None: mastodon_ids.add(mid)
            
            texts = [screenname, bio]
            if pinned_tweet is not None: texts.append(pinned_tweet.text)
            for text in texts:
                for _, h_str, _, u_str in _id_pattern2.findall(text):
                    mid = make_mastodon_id(u_str, h_str)
                    if mid is not None: mastodon_ids.add(mid)
                    
            mastodon_ids = list(mastodon_ids)
            mastodon_ids.sort(key=(lambda mid: str(mid)))
            
            if not mastodon_ids:
              extras = list()
              for d in u.description.splitlines():
                  if _keyword_pattern.match(d): extras.append(d)
              if not extras: extras = None
              
            if mastodon_ids:
                results1.append(UserResult(uid, name, screenname, bio, mastodon_ids, extras))
            elif extras is not None:
                results2.append(UserResult(uid, name, screenname, bio, mastodon_ids, extras))
       
        if next_token is None:
            break

    results1.sort(key = (lambda u: u.screenname.lower()))
    results2.sort(key = (lambda u: u.screenname.lower()))

    return (results1, results2, n_users)

