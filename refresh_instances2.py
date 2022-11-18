# Updates table of known instances with data from Fedifinder

import os
import json
import psycopg2
import requests

api_endpoint = 'https://fedifinder.glitch.me/api/known_instances.json'
create_command = '''CREATE TABLE IF NOT EXISTS instances (name TEXT NOT NULL PRIMARY KEY);'''

def env(s):
   if s not in os.environ:
       print('Missing environment variable: ', s)
   return os.environ[s]
   
db_user = 'debirdify'
db_password = env('DEBIRDIFY_INSTANCE_DB_PASSWORD')

response = requests.get(url=api_endpoint, allow_redirects=True)

data = response.json()
    
def parse_instance(dat):
    try:
        name = dat['domain']
        local_domain = dat['local_domain']
        if not dat['part_of_fediverse']: return None
        if 'updatedAt' in dat:
            last_update = dat['updatedAt']
        else:
            last_update = None
        registrations_open = dat['openRegistrations']
        software = dat['software_name']
        software_version = dat['software_version']
        users = dat['users_total']
        users_m = dat['users_activeMonth']
        users_hy = dat['users_activeHalfyear']
        local_posts = dat['localPosts']
        registrations_open = dat['openRegistrations']
        return (name, local_domain, software, software_version, registrations_open, users, users_m, users_hy, local_posts, last_update)
    except Exception as e:
        print('Error parsing JSON:', e)
        return None
    
instances = [i for dat in data if (i := parse_instance(dat)) is not None]

con = psycopg2.connect(f"dbname=debirdify user={db_user} host=localhost password={db_password}")
#con.execute(create_command)
with con.cursor() as cur:
    cur.executemany('INSERT INTO instances (name, local_domain, software, software_version, registrations_open, users, active_month, active_halfyear, local_posts, last_update, dead, up) VALUES (%s, %s, %s, %s, CAST(%s AS INTEGER), %s, %s, %s, %s, %s, 0, 1) ON CONFLICT(name) DO UPDATE SET name = excluded.name, local_domain = excluded.local_domain, software = excluded.software, software_version = excluded.software_version, registrations_open = excluded.registrations_open, users = excluded.users, active_month = excluded.active_month, active_halfyear = excluded.active_halfyear, local_posts = excluded.local_posts, last_update = excluded.last_update, dead = 0, up = 1',
      instances)
con.commit()
con.close()

