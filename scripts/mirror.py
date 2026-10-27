"""Mirror public, content-addressed CD2 update bytes. Never signs or selects a client release."""
import base64
import hashlib
import http.client
import json
import os
import re
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = 'erotics1/cd2-updates'
ORIGIN = 'https://cd2game.com'
INDEX = 'channels/blobs-v1.json'
HASH = re.compile(r'[0-9a-f]{64}')
TAG = re.compile(r'mirror-[A-Za-z0-9][A-Za-z0-9._-]{0,179}')
BUILD = re.compile(r'cd20-bt-base-[0-9]{8}-r[0-9]+[a-z]?')
MAX_ASSET = 2**31 - 1

def valid_entry(row):
    return (isinstance(row, dict) and isinstance(row.get('sha256'), str)
            and HASH.fullmatch(row['sha256']) is not None
            and type(row.get('size')) is int and 0 < row['size'] <= MAX_ASSET
            and isinstance(row.get('tag'), str) and TAG.fullmatch(row['tag']) is not None)

def validate_dataset(data):
    if (not isinstance(data, dict) or data.get('kind') != 'cd20-bt-incremental-v1'
        or not BUILD.fullmatch(data.get('targetBuildId', ''))
        or not HASH.fullmatch(data.get('targetManifestSha256', ''))
        or not isinstance(data.get('available'), list) or len(data['available']) > 1000):
        raise ValueError('Invalid BT dataset')
    result = []
    seen = set()
    for row in data['available']:
        if not valid_entry(dict(row, tag='mirror-validation')) or row['sha256'] in seen:
            raise ValueError('Invalid, oversized or repeated artifact')
        seen.add(row['sha256'])
        result.append((row['sha256'], row['size']))
    return result

def api(path, data=None, method=None, missing=False):
    token = os.environ['GH_TOKEN']
    req = urllib.request.Request('https://api.github.com/repos/' + REPO + path,
        data=None if data is None else json.dumps(data).encode(), method=method,
        headers={'Authorization':'Bearer '+token,'Accept':'application/vnd.github+json',
                 'X-GitHub-Api-Version':'2022-11-28','User-Agent':'CD2-public-mirror',
                 'Content-Type':'application/json'})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return json.load(r)
    except urllib.error.HTTPError as error:
        if error.code == 404 and missing: return None
        raise RuntimeError('GitHub API status ' + str(error.code)) from None

def public_json(url):
    req = urllib.request.Request(url, headers={'User-Agent':'CD2-public-mirror'})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = r.read(2*1024*1024+1)
        if len(data) > 2*1024*1024: raise ValueError('Metadata too large')
        return json.loads(data)

RETRY_STATUS = {429, 502, 503, 504}
RETRY_SECONDS = 1800

def download(sha, size, path, sleep=time.sleep, clock=time.monotonic):
    # The origin serves at most a few downloads at once and answers 429 when busy (players updating): wait and retry, never give up early.
    deadline = clock() + RETRY_SECONDS
    while True:
        try:
            return download_once(sha, size, path)
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUS or clock() >= deadline: raise
            wait = error.headers.get('Retry-After', '') if error.headers else ''
            wait = min(int(wait), 60) if wait.isdigit() else 10
        except (urllib.error.URLError, TimeoutError, ConnectionError, http.client.HTTPException):
            if clock() >= deadline: raise
            wait = 15
        print('Origin busy or unreachable for', sha, '- retrying in', wait, 's', flush=True)
        sleep(max(wait, 2))

def download_once(sha, size, path):
    digest = hashlib.sha256()
    count = 0
    req = urllib.request.Request(ORIGIN+'/launcher/update/files/'+sha,
                                 headers={'User-Agent':'CD2-public-mirror'})
    with urllib.request.urlopen(req, timeout=180) as r, path.open('wb') as out:
        while chunk := r.read(1024*1024):
            count += len(chunk)
            if count > size: raise ValueError('Source exceeds advertised size')
            digest.update(chunk)
            out.write(chunk)
    if count != size or digest.hexdigest() != sha:
        raise ValueError('Source SHA-256 or size mismatch')

def upload(release_id, sha, path, expected_size):
    # Stream one verified asset, with credentials sent only to GitHub's upload API.
    conn = http.client.HTTPSConnection('uploads.github.com', timeout=180)
    try:
        conn.putrequest('POST', f'/repos/{REPO}/releases/{release_id}/assets?name={sha}.bin')
        conn.putheader('Authorization', 'Bearer '+os.environ['GH_TOKEN'])
        conn.putheader('User-Agent', 'CD2-public-mirror')
        conn.putheader('Accept', 'application/vnd.github+json')
        conn.putheader('Content-Type', 'application/octet-stream')
        conn.putheader('Content-Length', str(expected_size))
        conn.endheaders()
        with path.open('rb') as source:
            while chunk := source.read(1024*1024): conn.send(chunk)
        response = conn.getresponse()
        data = response.read(1024*1024)
        if response.status != 201: raise RuntimeError('Upload status '+str(response.status))
        asset = json.loads(data)
        if asset['size'] != expected_size or asset.get('digest') != 'sha256:'+sha:
            raise ValueError('GitHub upload digest mismatch')
    finally: conn.close()

def run():
    if os.environ.get('GITHUB_REPOSITORY') != REPO:
        raise ValueError('This publisher runs only in the official updates repository')
    info = public_json(ORIGIN+'/launcher/update/info')
    dataset = info['dataset']
    wanted = validate_dataset(dataset)
    launcher = json.loads(base64.b64decode(info['launcher']['payload'], validate=True))
    if (launcher.get('schemaVersion') != 2 or launcher.get('kind') != 'cd-launcher-bt'
        or launcher.get('family') != 'cd20-bt' or not re.fullmatch(r'[0-9]+\.[0-9]+\.[0-9]+', launcher.get('version',''))):
        raise ValueError('Invalid launcher family')
    if not valid_entry(dict(launcher, tag='mirror-validation')): raise ValueError('Invalid launcher artifact')
    wanted.append((launcher['sha256'], launcher['size']))
    previous = api('/contents/'+INDEX, missing=True)
    catalog = {'schemaVersion':1,'repository':REPO,'files':[]}
    if previous:
        catalog = json.loads(base64.b64decode(previous['content']))
        if (catalog.get('schemaVersion') != 1 or catalog.get('repository') != REPO
            or len(catalog['files']) > 4096 or not all(valid_entry(x) for x in catalog['files'])):
            raise ValueError('Invalid existing mirror catalog')
    known = {row['sha256']:row for row in catalog['files']}
    pending = [(sha,size) for sha,size in dict(wanted).items() if sha not in known]
    if not pending:
        print('All current artifacts are already mirrored; no channel or release changes.')
        return
    tag = 'mirror-'+dataset['targetBuildId']+'-'+dataset['targetManifestSha256'][:12]+'-launcher-'+launcher['version']
    release = api('/releases/tags/'+tag, missing=True)
    if release is None:
        release = api('/releases', {'tag_name':tag,'target_commitish':'main','name':'CD2 update mirror — '+dataset['targetBuildId'],
            'body':'Public content-addressed transport mirror. The official signed launcher manifests authorize installation. No server source or private keys are included.',
            'draft':True,'prerelease':False,'make_latest':'false'})
    assets = {a['name']:a for a in release['assets']}
    with tempfile.TemporaryDirectory(prefix='cd2-mirror-') as folder:
        for sha,size in pending:
            name = sha+'.bin'
            if name in assets:
                a = assets[name]
                if a['size'] != size or a.get('digest') != 'sha256:'+sha:
                    raise ValueError('Existing release asset differs; refusing overwrite')
            else:
                if not release['draft']: raise ValueError('Published release is incomplete; refusing mutation')
                path = Path(folder)/name
                download(sha, size, path)
                upload(release['id'], sha, path, size)
                path.unlink()
            known[sha] = {'sha256':sha,'size':size,'tag':tag}
            print('Verified and mirrored', sha, size, flush=True)
    if release['draft']: api('/releases/'+str(release['id']), {'draft':False,'make_latest':'false'}, method='PATCH')
    catalog['files'] = sorted(known.values(), key=lambda r:r['sha256'])
    catalog['sourceBuildId'] = dataset['targetBuildId']
    content = (json.dumps(catalog,indent=2)+'\n').encode()
    payload = {'message':'Publish verified CD2 mirror catalog [skip ci]','content':base64.b64encode(content).decode(),'branch':'main'}
    if previous: payload['sha'] = previous['sha']
    api('/contents/'+INDEX, payload, method='PUT')
    print('Published catalog with', len(catalog['files']), 'verified artifacts.')

if __name__ == '__main__': run()
