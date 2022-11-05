import traceback
import os
import json
import sqlite3
import requests
from concurrent.futures import ThreadPoolExecutor
import time
import sys
from alive_progress import alive_bar

env_db_file = 'DEBIRDIFY_INSTANCE_DB'

max_failures = 3
overall_timeout = 3600
max_workers = 4
timeout = 5
instance_limit = 200
if 'DEBIRDIFY_TEST_INSTANCE_WORKERS' in os.environ:
    max_workers = os.environ['DEBIRDIFY_TEST_INSTANCE_WORKERS']

def env(s):
   if s not in os.environ:
       print('Missing environment variable: ', s)
   return os.environ[s]
   
db_file = env(env_db_file)

con = sqlite3.connect(db_file)
cur = con.cursor()
cur.execute("SELECT name FROM instances WHERE last_update is NULL OR last_update <= DATE('now', '-1 day') ORDER BY RANDOM() LIMIT ?", (instance_limit,))
#cur.execute("SELECT name FROM instances WHERE software is NULL")
#cur.execute("SELECT name FROM instances")

hosts = cur.fetchall()

max_nodeinfo_tries = 5

def mk_int(x):
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

def parse_json(name, json):
    def retrieve(xs):
        dat = json
        for x in xs:
            if dat is None: return None
            if x in dat:
                dat = dat[x]
            else:
                return None
        return dat
    
    result = dict()
    result['name'] = name
    result['software'] = retrieve(['software', 'name'])
    result['software_version'] = retrieve(['software', 'version'])
    result['registrations_open'] = mk_bool(retrieve(['openRegistrations']))
    result['users'] = mk_int(retrieve(['usage', 'users', 'total']))
    result['active_month'] = mk_int(retrieve(['usage', 'users', 'activeMonth']))
    result['active_halfyear'] = mk_int(retrieve(['usage', 'users', 'activeHalfyear']))
    result['local_posts'] = mk_int(retrieve(['usage', 'localPosts']))
    return result

def test_host(row):
    name = row[0]
    data = None
    error = None
    try:
        response = requests.get(url=f'https://{name}/.well-known/nodeinfo', headers = {'Accept': 'application/json'}, timeout=timeout, allow_redirects=True)
        nodeinfo_tries = 1
        links = response.json().get('links') or []
        for link in links:
            if nodeinfo_tries > max_nodeinfo_tries:
                if 'mastodon' in name: print(name, 'Nodeinfo tries exeeded')
                break
            if 'href' not in link: continue
            nodeinfo_tries += 1
            try:
                response = requests.get(url=link['href'], headers = {'Accept': 'application/json'}, timeout=timeout, allow_redirects=True)
                json = response.json()
                if 'activitypub' in json['protocols']:
                    data = parse_json(name, json)
                    break
            except Exception as e:
                error = e
                pass
    except Exception as e:
        error = e
        status = 'error'
    return (name, data, error)

def dowork(n, callback):
    if sys.stdout.isatty():
        with alive_bar(n) as bar:
            result = callback(bar)
    else:
        result = callback(lambda: ())
    return result

results = list()
new_hosts = list()
bad_hosts = list()
errors = dict()

with ThreadPoolExecutor(max_workers = max_workers) as executor:
    n_hosts = len(hosts)
    def callback(bar):
        for name, data, error in executor.map(test_host, hosts, timeout=overall_timeout):
            bar()
            if data is None:
                bad_hosts.append(name)
                errors[name] = error
            else:
                results.append(data)
    dowork(n_hosts, callback)


con.executemany("UPDATE instances SET dead=1, up=0, last_update=CURRENT_TIMESTAMP, error=? WHERE name=?", [(str(err), name) for name, err in errors.items()])

def mk_row(d):
    return (d['software'], d['software_version'], d['registrations_open'], d['users'], d['active_month'], d['active_halfyear'], d['local_posts'], d['name'])

rows = [mk_row(d) for d in results]
con.executemany("UPDATE instances SET software=?, software_version=?, registrations_open=?, users=?, active_month=?, active_halfyear=?, local_posts=?, up=1, dead=0, last_update=CURRENT_TIMESTAMP WHERE name=?", rows)
con.commit()
con.close()



