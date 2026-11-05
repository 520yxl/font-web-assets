"""Discover real font files in a separate repository without copying originals here."""
import hashlib
import json
import os
import re
import time
import urllib.parse
import urllib.request
from pathlib import PurePosixPath

from convert import ROOT, fetch, read_json, write_json


def api(repository, path):
    headers = {'User-Agent': 'font-web-assets', 'Accept': 'application/vnd.github+json'}
    if os.environ.get('GITHUB_TOKEN'):
        headers['Authorization'] = 'Bearer ' + os.environ['GITHUB_TOKEN']
    request = urllib.request.Request('https://api.github.com/repos/' + repository + '/' + path, headers=headers)
    for attempt in range(3):
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                return json.load(response)
        except OSError:
            if attempt == 2:
                raise
            time.sleep(2 * (attempt + 1))


def nearby_license(path, blobs):
    # Search the font directory and parent project directories, never a global root license.
    parent = PurePosixPath(path).parent
    while len(parent.parts) >= 2:
        for name in ('OFL.txt', 'OFL.TXT', 'LICENSE.txt', 'LICENSE', 'LICENSE.md', 'APACHE.txt'):
            candidate = str(parent / name)
            if candidate in blobs:
                return candidate
        parent = parent.parent
    return None


def license_type(data):
    text = data.decode('utf-8-sig').upper()
    if 'SIL OPEN FONT LICENSE' in text and 'VERSION 1.1' in text:
        return 'OFL-1.1'
    if 'APACHE LICENSE' in text and 'VERSION 2.0' in text:
        return 'Apache-2.0'
    if 'PERMISSION IS HEREBY GRANTED, FREE OF CHARGE' in text and 'THE SOFTWARE IS PROVIDED' in text:
        return 'MIT'
    return None


def sync():
    config = read_json(ROOT / 'source-repository.json', {})
    repo, ref = config['repository'], config.get('ref', 'main')
    if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+', repo):
        raise ValueError('Invalid source repository')
    commit = api(repo, 'commits/' + urllib.parse.quote(ref, safe=''))['sha']
    tree = api(repo, 'git/trees/' + commit + '?recursive=1')
    if tree.get('truncated'):
        raise ValueError('Source tree truncated; refusing incomplete discovery')
    blobs = {entry['path']: entry for entry in tree['tree'] if entry['type'] == 'blob'}
    base = 'https://raw.githubusercontent.com/' + repo + '/' + commit + '/'
    raw = lambda path: base + urllib.parse.quote(path, safe='/')
    # Source index supplies SHA256 and names. Only paths actually in this repo are used.
    index = json.loads(fetch(raw('dist/fonts.json'), 80 * 1024 * 1024))
    if isinstance(index, dict):
        index = index['fonts']
    previous = {item['id']: item for item in read_json(ROOT / 'sources.json', [])}
    sources, skipped, licenses, seen = [], [], {}, set()
    for font in index:
        path, sha = font.get('path', ''), font.get('sha256', '')
        if path not in blobs or PurePosixPath(path).suffix.lower() not in {'.ttf', '.otf', '.woff', '.woff2'}:
            continue
        if not re.fullmatch(r'[0-9a-f]{64}', sha) or sha in seen:
            continue
        seen.add(sha)
        identifier = sha[:32]
        old = previous.get(identifier)
        license_path = nearby_license(path, blobs)
        embedded = font.get('license', '')
        if license_path:
            if license_path not in licenses:
                data = fetch(raw(license_path), 1024 * 1024)
                licenses[license_path] = (license_type(data), hashlib.sha256(data).hexdigest())
            kind, license_sha = licenses[license_path]
        else:
            kind = license_type(embedded.encode('utf-8'))
            license_sha = hashlib.sha256(embedded.encode('utf-8')).hexdigest()
        if not kind:
            skipped.append({'path': path, 'reason': 'license needs separate handling'})
            continue
        # Retain immutable URLs when source blobs are unchanged, avoiding reconversion every commit.
        if old and old.get('source_blob') == blobs[path]['sha'] and old.get('license_sha256') == license_sha:
            sources.append(old)
            continue
        sources.append({
            'id': identifier, 'name': font.get('full_name') or font.get('family') or PurePosixPath(path).stem,
            'url': raw(path), 'sha256': sha, 'source_blob': blobs[path]['sha'],
            'source_url': 'https://github.com/' + repo + '/blob/' + commit + '/' + urllib.parse.quote(path, safe='/'),
            'license': kind, 'license_url': raw(license_path) if license_path else '',
            'license_text': '' if license_path else embedded, 'license_sha256': license_sha,
            'weight': font.get('weight_class', 400),
            'style': 'italic' if 'italic' in font.get('style', '').lower() else 'normal',
            'approved': True,
        })
    write_json(ROOT / 'sources.json', sorted(sources, key=lambda item: item['id']))
    report = {'repository': repo, 'commit': commit, 'available': len(sources), 'skipped': skipped}
    write_json(ROOT / 'source-sync-report.json', report)
    print(json.dumps({'repository': repo, 'commit': commit, 'available': len(sources), 'skipped': len(skipped)}))


if __name__ == '__main__':
    sync()
