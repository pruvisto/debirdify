from django.db import connection
import json
import datetime
import secrets
import psycopg2

def _format_datetime(d):
    if d is None:
        return None
    return d.strftime('%d.%m.%Y %H:%M:%S')

class BatchJob:
    def __init__(self, *, id, text_id, name, size, t_launched, t_updated = None, t_completed = None, t_aborted = None, progress = None):
        self.id = id
        self.text_id = text_id
        self.name = name
        self.t_launched = t_launched
        self.t_launched_str = _format_datetime(self.t_launched)
        self.t_completed = t_completed
        self.t_completed_str = _format_datetime(self.t_completed)
        self.t_updated = t_updated
        self.t_updated_str = _format_datetime(self.t_updated)
        self.t_aborted = t_aborted
        self.t_aborted_str = _format_datetime(self.t_aborted)
        self.progress = progress
        if self.progress is None: self.progress = 0
        self.size = size
        self.completed = (t_completed is not None)
        self.aborted = (t_aborted is not None)
        self.running = not self.aborted and not self.completed
        self.progress_percentage = '%.1f' % (self.progress / self.size * 100)

def get(uid):
    uid = str(uid)
    with connection.cursor() as cur:
        cur.execute('SELECT id, name, time_launched, time_updated, time_completed, time_aborted, progress, size, text_id FROM batch_jobs WHERE uid=%s ORDER BY time_launched DESC LIMIT 1', [uid])
        row = cur.fetchone()
        if not row: return None
        return BatchJob(id = row[0], name = row[1], t_launched = row[2], t_updated = row[3], t_completed = row[4], t_aborted = row[5], progress = row[6], size = row[7], text_id = row[8])

def delete_all(uid):
    uid = str(uid)
    with connection.cursor() as cur:
        cur.execute('DELETE FROM batch_job_requests AS R WHERE R.job_id IN (SELECT J.id FROM batch_jobs AS J WHERE J.uid=%s)', [uid])
        cur.execute('DELETE FROM batch_jobs WHERE uid=%s', [uid])

def _mk_request_from_user(job_id, u):
    if u.uid is not None:
        return (job_id, str(u.uid), None)
    elif u.screenname is not None:
        return (job_id, None, str(u.screenname))
    else:
        return None

def launch(*, uid, access_credentials, name, requested_users):
    uid = str(uid)
    name = str(name)
    size = len(requested_users)
    with connection.cursor() as cur:
        while True:
            try:
                text_id = secrets.token_urlsafe(32)
                cur.execute('INSERT INTO batch_jobs (name, uid, size, access_credentials, text_id) VALUES (%s, %s, %s, %s, %s) RETURNING id', [name, uid, size, access_credentials, text_id])
                break
            except psycopg2.errors.UniqueViolation:
                pass
        job_id = cur.fetchone()[0]
        reqs = [x for u in requested_users if (x := _mk_request_from_user(job_id, u)) is not None]
        cur.executemany('INSERT INTO batch_job_requests (job_id, uid, username) VALUES (%s, %s, %s)', reqs)
        return BatchJob(id = job_id, text_id = text_id, size = size, name = name, t_launched = datetime.datetime.now())

