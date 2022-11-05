import os
import json
import sqlite3
import requests

env_db_file = 'DEBIRDIFY_INSTANCE_DB'
env_api_token = 'DEBIRDIFY_INSTANCE_API_TOKEN'

api_endpoint = 'https://instances.social/api/1.0/instances/list?count=0'
create_command = '''CREATE TABLE IF NOT EXISTS instances (name TEXT NOT NULL PRIMARY KEY);'''

def env(s):
   if s not in os.environ:
       print('Missing environment variable: ', s)
   return os.environ[s]
   
db_file = env(env_db_file)
api_token = env(env_api_token)

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
    except:
        print('Error parsing JSON:', dat)
        return None
    
instances = [i for dat in data['instances'] if (i := parse_instance(dat)) is not None]

con = sqlite3.connect(db_file)
#con.execute(create_command)
con.executemany('INSERT INTO instances (name, dead, up, uptime, last_update, registrations_open, users) VALUES (?, ?, ?, ?, ?, ?, ?) ON CONFLICT(name) DO UPDATE SET uptime=IFNULL(excluded.uptime, uptime)', instances)
con.commit()
con.close()

