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
timeout = 10
overall_timeout = 3600

max_workers = 8
if 'DEBIRDIFY_TEST_INSTANCE_WORKERS' in os.environ:
    max_workers = os.environ['DEBIRDIFY_TEST_INSTANCE_WORKERS']

def env(s):
   if s not in os.environ:
       print('Missing environment variable: ', s)
   return os.environ[s]
   
db_file = env(env_db_file)

con = sqlite3.connect(db_file)
cur = con.cursor()
cur.execute('SELECT name, failures FROM unknown_hosts')

hosts = cur.fetchall()

max_nodeinfo_tries = 3

def test_host(row):
    name, failures = row
    status = 'notsupported'
    try:
        response = requests.get(url=f'https://{name}/.well-known/nodeinfo', headers = {'Accept': 'application/json'}, timeout=timeout, allow_redirects=True)
        nodeinfo_tries = 1
        for link in response.json()['links']:
            if nodeinfo_tries > max_nodeinfo_tries: break
            if 'href' not in link: continue
            nodeinfo_tries += 1
            response = requests.get(url=link['href'], headers = {'Accept': 'application/json'}, timeout=timeout, allow_redirects=True)
            data = response.json()
            if 'activitypub' in data['protocols']:
                status = 'supported'
                break
    except:
        status = 'error'
    return (name, failures, status)

def dowork(n, callback):
    if sys.stdout.isatty():
        with alive_bar(n) as bar:
            result = callback(bar)
    else:
        result = callback(lambda: ())
    return result

new_hosts = list()
new_bad_hosts = list()
with ThreadPoolExecutor(max_workers = max_workers) as executor:
    n_hosts = len(hosts)
    def callback(bar):
        for name, failures, status in executor.map(test_host, hosts, timeout=overall_timeout):
            bar()
            if status == 'supported':
                new_hosts.append(name)
                con.execute('INSERT INTO instances (name) VALUES (?) ON CONFLICT DO NOTHING', (name,))
                con.execute('DELETE FROM unknown_hosts WHERE name=?', (name,))
                con.execute('DELETE FROM bad_hosts WHERE name=?', (name,))
            elif failures >= max_failures:
                new_bad_hosts.append(name)
                con.execute('INSERT INTO bad_hosts (name) VALUES (?) ON CONFLICT DO NOTHING', (name,))
                con.execute('DELETE FROM unknown_hosts WHERE name=?', (name,))
            else:
                con.execute('UPDATE unknown_hosts SET failures = failures + 1 WHERE name=?', (name,))
    dowork(n_hosts, callback)
    
con.commit()
con.close()

if new_hosts:
    print('New hosts discovered:')
    for host in new_hosts: print(host)
    print('')

if new_bad_hosts:
    print('New bad hosts discovered:')
    for host in new_bad_hosts: print(host)
    print('')


