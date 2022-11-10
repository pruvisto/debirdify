import os
import json
import psycopg2
import requests

env_api_token = 'DEBIRDIFY_INSTANCE_API_TOKEN'

api_endpoint = 'https://instances.social/api/1.0/instances/list?count=0'
create_command = '''CREATE TABLE IF NOT EXISTS instances (name TEXT NOT NULL PRIMARY KEY);'''

def env(s):
   if s not in os.environ:
       print('Missing environment variable: ', s)
   return os.environ[s]
   
api_token = env(env_api_token)
db_user = 'debirdify'
db_password = env('DEBIRDIFY_INSTANCE_DB_PASSWORD')

response = requests.get(url=api_endpoint, headers = {'authorization': 'Bearer ' + api_token}, allow_redirects=True)

data = response.json()
if 'instances' not in data:
    print('Invalid instance list.')
    exit(1)
    
def parse_instance(dat):
    try:
        name = dat['name']
        dead = dat['dead']
        up = dat['up']
        uptime = dat['uptime']
        last_update = dat['checked_at']
        registrations_open = dat['open_registrations']
        users = dat['users']
        return (name, dead, up, uptime, last_update, registrations_open, users)
    except Exception as e:
        print('Error parsing JSON:', e)
        return None
    
instances = [i for dat in data['instances'] if (i := parse_instance(dat)) is not None]

con = psycopg2.connect(f"dbname=debirdify user={db_user} password={db_password}")
#con.execute(create_command)
with con.cursor() as cur:
    cur.executemany('INSERT INTO instances (name, dead, up, uptime, last_update, registrations_open, users) VALUES (%s, CAST(%s AS INTEGER), CAST(%s AS INTEGER), %s, %s, CAST(%s AS INTEGER), %s) ON CONFLICT(name) DO UPDATE SET uptime=COALESCE(excluded.uptime, instances.uptime)', instances)
con.commit()
con.close()

