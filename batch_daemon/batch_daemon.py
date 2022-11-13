import psycopg2
import tweepy
import time
import os
import extract_mastodon_ids
import traceback

def env(s):
   if s not in os.environ:
       print('Missing environment variable: ', s)
   return os.environ[s]

TWITTER_CONSUMER_CREDENTIALS = [x.strip() for x in env('DEBIRDIFY_CONSUMER_CREDENTIALS').split(':')]
if len(TWITTER_CONSUMER_CREDENTIALS) != 2:
    raise MissingEnvVariable('DEBIRDIFY_CONSUMER_CREDENTIALS')

def mk_client(access_credentials):
    access_credentials = access_credentials.split(':')
    return tweepy.Client(
        consumer_key=TWITTER_CONSUMER_CREDENTIALS[0],
        consumer_secret=TWITTER_CONSUMER_CREDENTIALS[1],
        access_token=access_credentials[0],
        access_token_secret=access_credentials[1])

        
db_user = 'debirdify'
db_password = env('DEBIRDIFY_INSTANCE_DB_PASSWORD')
con = psycopg2.connect(f"dbname=debirdify user={db_user} host=localhost password={db_password}")
sleep_time = 1
MAX_SLEEP_TIME = 4

def reset_sleep_time():
    global sleep_time
    sleep_time = 1

def wait():
    global sleep_time
    time.sleep(sleep_time)
    if sleep_time < MAX_SLEEP_TIME: sleep_time *= 2


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

def handle_requests(*, client, by_id, requests):
    if by_id:
        resp = client.get_users(
                ids = [uid for _, uid in requests], 
                user_auth=True, 
                user_fields=['name', 'username', 'description', 'entities', 'location', 'pinned_tweet_id'],
                tweet_fields=['entities'], 
                expansions='pinned_tweet_id')
    else:
        resp = client.get_users(
                usernames = [str(x) for _, x in requests], 
                user_auth=True, 
                user_fields=['name', 'username', 'description', 'entities', 'location', 'pinned_tweet_id'],
                tweet_fields=['entities'], 
                expansions='pinned_tweet_id')

    results = extract_mastodon_ids.Results()
    extract_mastodon_ids.extract_mastodon_ids_from_users(client, lambda x: None, resp, results, known_host_callback=known_host_callback)
    
    if by_id:
        result_map = {str(u.uid): u for u in results.results.values()}
    else:
        result_map = {u.screenname: u for u in results.results.values()}
        
    def mk_result(x):
        if x in result_map:
            return result_map[x].to_json()
        else:
            return '{}'
    
    return [(mk_result(x), rid) for rid, x in requests]

def delete_orphans(con):
    with con.cursor() as cur:
        cur.execute('DELETE FROM batch_job_requests WHERE job_id NOT IN (SELECT id FROM batch_jobs)')
        con.commit()

def handle_job(job_id, name, access_credentials):
    job_str = f'#{job_id}'
    print(f'Working on job {job_str}...')
    client = mk_client(access_credentials)
    
    with con.cursor() as cur:
        cur.execute('SELECT id, uid FROM batch_job_requests WHERE job_id=%s AND uid IS NOT NULL AND result IS NULL LIMIT 100', [job_id])
        rows = cur.fetchall()
        try:
            if rows:
                results = handle_requests(client = client, by_id = True, requests = rows)
                cur.executemany('UPDATE batch_job_requests SET result=%s WHERE id=%s', results)
            else:
                cur.execute('SELECT id, username FROM batch_job_requests WHERE job_id=%s AND username IS NOT NULL AND result IS NULL LIMIT 100', [job_id])
                rows = cur.fetchall()
                if rows:
                    results = handle_requests(client = client, by_id = False, requests = rows)
                    cur.executemany('UPDATE batch_job_requests SET result=%s WHERE id=%s', results)
        except tweepy.TooManyRequests:
            pass
        except Exception as e:
            cur.execute('UPDATE batch_jobs SET time_aborted = NOW(), error = %s WHERE id=%s', [str(e), job_id])
            print('Aborting job {job_str}. Cause: {e}')
            traceback.print_exc()
            return
        
        cur.execute('SELECT COUNT(id) FROM batch_job_requests WHERE job_id=%s AND result IS NULL', [job_id])
        cnt = cur.fetchone()[0]
        cur.execute('UPDATE batch_jobs SET time_updated = NOW(), progress=size-%s WHERE id=%s ', [cnt, job_id])
        if cnt == 0:
            cur.execute('UPDATE batch_jobs SET time_completed = NOW() WHERE id=%s', [job_id])
            print(f'Job completed.')
        else:
            print(f'{cnt} requests remaining.')
    

def run():
    global sleep_time
    while True:
        with con.cursor() as cur:
            cur.execute('SELECT id, name, access_credentials FROM batch_jobs WHERE time_completed is NULL and time_aborted is NULL ORDER BY time_updated ASC LIMIT 1')
            row = cur.fetchone()
            if row is None:
                wait()
            else:
                sleep_time = 1
                handle_job(row[0], row[1], row[2])
                con.commit()
            
run()
