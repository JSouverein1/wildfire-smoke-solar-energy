"""Safe downloads and small resumable data records."""
from __future__ import annotations
import json
import math
import time
from pathlib import Path
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry


def session_with_retries():
    s = requests.Session()
    s.headers.update({'User-Agent': 'AcademicResearchWildfireSmokeSolar/1.0'})
    adapter = HTTPAdapter(max_retries=Retry(total=3, backoff_factor=1.2,
                      status_forcelist=[429,500,502,503,504]))
    s.mount('https://', adapter)
    return s


def download(session, url, path, *, kind='binary'):
    """Return status 'ok', 'http_404', or 'download_error'; stream to .part then rename.
    Existing nonempty files are not re-downloaded. Never cache HTML error pages.
    """
    path = Path(path)
    if path.exists() and path.stat().st_size:
        return 'ok'
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.part')
    try:
        with session.get(url, stream=True, timeout=(20, 120)) as r:
            if r.status_code == 404:
                return 'http_404'
            r.raise_for_status()
            if 'text/html' in r.headers.get('Content-Type', '').lower():
                raise ValueError('Received HTML instead of data')
            with temp.open('wb') as handle:
                for chunk in r.iter_content(chunk_size=1024*1024):
                    if chunk: handle.write(chunk)
            if not temp.exists() or temp.stat().st_size == 0:
                raise ValueError('Empty download')
            if kind == 'zip':
                with temp.open('rb') as f:
                    if f.read(4) != b'PK\x03\x04':
                        raise ValueError('Not a ZIP file')
            if kind == 'text':
                with temp.open('rb') as f:
                    if b'<' in f.read(50):
                        raise ValueError('Text appears to be an HTML error page')
            temp.replace(path)
            return 'ok'
    except (requests.RequestException, ValueError, OSError) as exc:
        print(f'  Download warning ({url}): {exc}', flush=True)
        return 'download_error'
    finally:
        temp.unlink(missing_ok=True)


def save_record(path, item):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.json.tmp')
    def sanitize(value):
        if isinstance(value, dict): return {k: sanitize(v) for k, v in value.items()}
        if isinstance(value, list): return [sanitize(v) for v in value]
        if isinstance(value, float) and not math.isfinite(value): return None
        return value
    temp.write_text(json.dumps(sanitize(item), allow_nan=False, indent=2), encoding='utf-8')
    temp.replace(path)


def get_record(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return None
