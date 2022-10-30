import re
import tweepy

forbidden_hosts = {'tiktok.com', 'www.tiktok.com', 'youtube.com', 'www.youtube.com', 'medium.com', 'www.medium.com', 'skeb.jp', 'pronouns.page', 'foundation.app', 'gamejolt.com'}

# Matches anything of the form @foo@bar.bla or foo@bar.social or foo@social.bar or foo@barmastodonbla
# We do not match everything of the form foo@bar or foo@bar.bla to avoid false positives like email addresses
_id_pattern1 = re.compile(r'(@[\w\-\.]+@[\w\-\.]+\.[\w\-\.]+|[\w\-\.]+@[\w\-\.]+\.social|[\w\-\.]+@social\.[\w\-\.]+|[\w\-\.]+@[\w\-\.]*mastodon[\w\-\.]+)', re.IGNORECASE)
_id_pattern2 = re.compile(r'\b(http://|https://)?([\w\-\.]+\.[\w\-\.]+)/(web/)?@([\w\-\.]+)/?\b', re.IGNORECASE)
_url_pattern = re.compile(r'^(http://|https://)([\w\-\.]+\.[\w\-\.]+)/(web/)?@([\w\-\.]+)/?$', re.IGNORECASE)

# Matches some key words that might occur in bios
_keyword_pattern = re.compile(r'.*(mastodon|toot|tröt).*', re.IGNORECASE)

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

max_pages = 5

def extract_urls(u):
    if u.entities is None: return []
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
    return results

def make_mastodon_id(u, h):
    if h.lower() in forbidden_hosts: return None
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
    
    while pages <= max_pages:
        resp = client.get_users_following(requested_user.id, max_results=1000, user_auth=True, user_fields=['name', 'username', 'description', 'entities'], pagination_token=next_token)

        try:
          next_token = resp.meta['next_token']
        except:
          next_token = None
        users = resp.data
        pages = pages + 1
        n_users += len(users)
        
        for u in users:
            uid = u.id
            name = u.name
            screenname = u.username
            bio = u.description
            mastodon_ids = set()
            mastodon_ids1 = [mid for s in _id_pattern1.findall(name) + _id_pattern1.findall(bio)
                                 if (mid := parse_mastodon_id(s)) is not None]
            for url in extract_urls(u):
                for _, h_str, _, u_str in _url_pattern.findall(url):
                    mid = make_mastodon_id(u_str, h_str)
                    if mid is not None: mastodon_ids1.append(mid)
            for _, h_str, _, u_str in _id_pattern2.findall(name):
                mid = make_mastodon_id(u_str, h_str)
                if mid is not None: mastodon_ids1.append(mid)
                                 
            mastodon_ids2 = [x for _, h_str, _, u_str in _id_pattern2.findall(screenname) + _id_pattern2.findall(bio) if (x := make_mastodon_id(u_str, h_str)) is not None]
            mastodon_ids = list(set(mastodon_ids1).union(set(mastodon_ids2)))
            extras = None
            
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

    return (results1, results2, n_users)

