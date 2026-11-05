"""Convert an approved, hash-pinned source list into persistent webfont assets."""
import argparse
import hashlib
import io
import json
import re
import time
import urllib.request
from pathlib import Path

import fontTools
from fontTools.ttLib import TTFont

ROOT = Path(__file__).resolve().parents[1]
MAX_BYTES = 19 * 1024 * 1024  # Leave room below the CDN's per-file limit.
RECIPE = 'full-woff2-v1-fonttools-' + fontTools.__version__


def read_json(path, default):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else default


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    temporary.replace(path)


def fetch(url, limit):
    # Only public, immutable GitHub raw URLs are accepted; no arbitrary hosts.
    if not re.fullmatch(r'https://raw\.githubusercontent\.com/[^/]+/[^/]+/[0-9a-f]{40}/.+', url):
        raise ValueError('Source must use a raw.githubusercontent.com URL pinned to a 40-character commit SHA')
    request = urllib.request.Request(url, headers={'User-Agent': 'font-web-assets'})
    with urllib.request.urlopen(request, timeout=90) as response:
        if response.geturl() != url:
            raise ValueError('Unexpected source redirect')
        data = response.read(limit + 1)
    if len(data) > limit:
        raise ValueError('Source exceeds size limit')
    return data


def validate_sources(sources):
    ids = set()
    for source in sources:
        identifier = source['id']
        if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,99}', identifier) or identifier in ids:
            raise ValueError('Invalid or duplicate font ID: ' + identifier)
        ids.add(identifier)
        if source.get('approved') is not True:
            continue
        for key in ('sha256', 'license_sha256'):
            if not re.fullmatch(r'[0-9a-f]{64}', source.get(key, '')):
                raise ValueError('Missing or invalid ' + key + ': ' + identifier)
        for key in ('name', 'url', 'license', 'source_url'):
            if not source.get(key):
                raise ValueError('Missing ' + key + ': ' + identifier)
        if not source.get('license_url') and not source.get('license_text'):
            raise ValueError('Missing license URL or embedded license text')


def convert(source):
    data = fetch(source['url'], 100 * 1024 * 1024)
    if hashlib.sha256(data).hexdigest() != source['sha256']:
        raise ValueError('Source SHA-256 mismatch')
    license_data = (source['license_text'].encode('utf-8') if source.get('license_text')
                    else fetch(source['license_url'], 1024 * 1024))
    if hashlib.sha256(license_data).hexdigest() != source['license_sha256']:
        raise ValueError('License SHA-256 mismatch')
    # Force a text license, rather than publishing arbitrary binary data.
    license_data.decode('utf-8-sig')
    with TTFont(io.BytesIO(data)) as original:
        notices = []
        if 'name' in original:
            for name in original['name'].names:
                if name.nameID in (0, 7, 13, 14):
                    value = name.toUnicode().strip()
                    if value and value not in notices:
                        notices.append(value)
        if notices:
            license_data += ('\n\nEmbedded font notices:\n' + '\n\n'.join(notices)).encode('utf-8')
        cmap = original.getBestCmap()
        if not cmap:
            raise ValueError('Font has no supported Unicode character map')
        glyphs = original.getGlyphOrder()
        axes = [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in original['fvar'].axes] if 'fvar' in original else []
        original.flavor = 'woff2'
        output = io.BytesIO()
        original.save(output)
    result = output.getvalue()
    if len(result) > MAX_BYTES:
        raise ValueError('WOFF2 exceeds 19 MiB delivery budget; needs subsetting/splitting')
    with TTFont(io.BytesIO(result)) as verified:
        verified.ensureDecompiled()
        actual_axes = [(a.axisTag, a.minValue, a.defaultValue, a.maxValue) for a in verified['fvar'].axes] if 'fvar' in verified else []
        if verified.getBestCmap() != cmap or verified.getGlyphOrder() != glyphs or actual_axes != axes:
            raise ValueError('Converted font differs in cmap, glyph order or variation axes')
    version = hashlib.sha256((source['sha256'] + RECIPE).encode()).hexdigest()[:20]
    folder = ROOT / 'fonts' / source['id'] / version
    folder.mkdir(parents=True, exist_ok=True)
    (folder / 'font.woff2').write_bytes(result)
    (folder / 'LICENSE.txt').write_bytes(license_data)
    return {
        'id': source['id'], 'name': source['name'], 'weight': source.get('weight', 400),
        'style': source.get('style', 'normal'), 'path': (folder / 'font.woff2').relative_to(ROOT).as_posix(),
        'license_path': (folder / 'LICENSE.txt').relative_to(ROOT).as_posix(),
        'source_url': source['source_url'], 'license': source['license'],
        'source_sha256': source['sha256'], 'sha256': hashlib.sha256(result).hexdigest(),
        'bytes': len(result), 'characters': len(cmap), 'recipe': RECIPE,
    }


def run(limit, seconds):
    sources = read_json(ROOT / 'sources.json', [])
    validate_sources(sources)
    state = read_json(ROOT / 'conversion-state.json', {})
    catalog = read_json(ROOT / 'catalog.json', {'schema_version': 1, 'fonts': []})
    entries = {entry['id']: entry for entry in catalog['fonts']}
    approved = {source['id'] for source in sources if source.get('approved') is True}
    entries = {key: value for key, value in entries.items() if key in approved}
    started = time.monotonic()
    attempted = 0
    for source in sources:
        if source.get('approved') is not True:
            continue
        fingerprint = hashlib.sha256(json.dumps({'source': source, 'recipe': RECIPE}, sort_keys=True).encode()).hexdigest()
        previous = state.get(source['id'], {})
        if previous.get('fingerprint') != fingerprint:
            previous = {}
        if previous.get('status') == 'done':
            entry = previous['entry']
            path = ROOT / entry['path']
            license_path = ROOT / entry['license_path']
            if path.is_file() and license_path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == entry['sha256']:
                entries[source['id']] = entry
                continue
        if previous.get('attempts', 0) >= 3:
            continue
        if attempted >= limit or time.monotonic() - started >= seconds:
            break
        attempted += 1
        record = {'fingerprint': fingerprint, 'attempts': previous.get('attempts', 0) + 1}
        try:
            entry = convert(source)
            record.update(status='done', entry=entry)
            entries[source['id']] = entry
            print('OK', source['id'], entry['bytes'], flush=True)
        except Exception as error:
            record.update(status='failed', error=str(error)[:500])
            print('FAILED', source['id'], record['error'], flush=True)
        state[source['id']] = record
        write_json(ROOT / 'conversion-state.json', state)
        write_json(ROOT / 'catalog.json', {'schema_version': 1, 'fonts': sorted(entries.values(), key=lambda x: x['id'])})
    write_json(ROOT / 'catalog.json', {'schema_version': 1, 'fonts': sorted(entries.values(), key=lambda x: x['id'])})
    print(json.dumps({'attempted': attempted, 'published': len(entries), 'approved': len(approved)}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int, default=20)
    parser.add_argument('--seconds', type=int, default=900)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100 or not 1 <= args.seconds <= 1200:
        parser.error('limit must be 1..100 and seconds 1..1200')
    run(args.limit, args.seconds)
