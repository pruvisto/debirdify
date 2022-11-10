from django.db import connection

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
    if x in (1, True, '1', 'true', 'True'): return True
    if x in (0, False, '0', 'false', 'False'): return False
    return None

class Instance:
    def __init__(self, host, local_domain, software, software_version, registrations_open, users, active_month, active_halfyear, local_posts, last_update, uptime, dead, up):
        host = host.lower()
        self.host = host
        if local_domain is None:
            self.local_domain = host
        else:
            self.local_domain = local_domain
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
        self.webfinger_url = f'https://{self.local_domain}/.well-known/webfinger'
        
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
    return Instance(name.lower(), None, None, None, None, None, None, None, None, None, None, None, None)

def get_instance(name):
    try:
        with connection.cursor() as cur:
            cur.execute('SELECT name, local_domain, software, software_version, registrations_open, users, active_month, active_halfyear, local_posts, last_update, uptime, dead, up FROM instances WHERE name=%s LIMIT 1', [name.lower()])
            row = cur.fetchone()
        if row is None: return naked_instance(name)
        i = Instance(row[0], row[1], row[2], row[3], row[4], row[5], row[6], row[7], row[8], row[9], row[10], row[11], row[12])
        return i
    except Exception as e:
        print(e)
        return naked_instance(name)

