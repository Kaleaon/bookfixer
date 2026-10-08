"""Helpers for the Royal Road setup dialog: talk to a FlareSolverr server the user runs, and edit the settings text.

Nothing here contacts a website except through the user's own FlareSolverr, and only when they press a test button.
"""
import configparser
import json
import re
import urllib.error
import urllib.request

SECTION = 'www.royalroad.com'
KEY = 'use_flaresolverr_proxy'
TEST_URL = 'https://www.royalroad.com/'
DOCKER_COMMAND = ('docker run -d --name=flaresolverr -p 127.0.0.1:8191:8191 -e LOG_LEVEL=info '
                  '--restart unless-stopped ghcr.io/flaresolverr/flaresolverr:latest')
CHALLENGE_MARKERS = ('just a moment', 'cf-mitigated', 'challenge-platform', 'checking your browser')


def settings_from_ini(text, section=SECTION):
    """Address, port and protocol FanFicFare will use: the site's section, then [defaults], then FanFicFare's own defaults."""
    found = {'address': 'localhost', 'port': '8191', 'protocol': 'http'}
    parser = configparser.ConfigParser(strict=False, interpolation=None)
    try:
        parser.read_string(text or '')
    except configparser.Error:
        return found
    for name in ('defaults', section):  # later wins
        if parser.has_section(name):
            for key in found:
                value = parser.get(name, f'flaresolverr_proxy_{key}', fallback='').strip()
                if value:
                    found[key] = value
    return found


def endpoint(settings):
    return f"{settings['protocol']}://{settings['address']}:{settings['port']}/v1"


def _post(settings, payload, timeout):
    request = urllib.request.Request(endpoint(settings), data=json.dumps(payload).encode(), method='POST',
                                     headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return json.loads(response.read().decode('utf-8', 'replace'))


def check_server(settings, timeout=10):
    """Ask FlareSolverr to list its sessions, which touches no website. Returns (ok, message)."""
    try:
        reply = _post(settings, {'cmd': 'sessions.list'}, timeout)
    except urllib.error.HTTPError as exc:
        return False, f'The server at {endpoint(settings)} answered HTTP {exc.code}, which is not what FlareSolverr does. Is something else using that port?'
    except (urllib.error.URLError, OSError):
        return False, (f'Nothing answered at {endpoint(settings)}. Start FlareSolverr (step 1), and check the address and port.')
    except ValueError:
        return False, f'Something answered at {endpoint(settings)} but it did not reply like FlareSolverr. Is another program using that port?'
    if isinstance(reply, dict) and reply.get('status') == 'ok':
        version = f" (version {reply['version']})" if reply.get('version') else ''
        return True, f'FlareSolverr is running{version} at {endpoint(settings)}.'
    message = reply.get('message') if isinstance(reply, dict) else ''
    return False, f'FlareSolverr answered but reported a problem: {message or reply}'


def fetch_through(settings, url=TEST_URL, max_timeout=60000):
    """Load one page through FlareSolverr and say what happened. Returns (ok, message)."""
    try:
        reply = _post(settings, {'cmd': 'request.get', 'url': url, 'maxTimeout': int(max_timeout)}, max_timeout / 1000 + 15)
    except urllib.error.HTTPError as exc:
        try:
            reply = json.loads(exc.read().decode('utf-8', 'replace'))
        except ValueError:
            return False, f'FlareSolverr answered HTTP {exc.code}.'
    except (urllib.error.URLError, OSError):
        return False, f'Could not reach FlareSolverr at {endpoint(settings)}. Run the first test.'
    except ValueError:
        return False, 'FlareSolverr sent a reply that could not be read.'
    if not isinstance(reply, dict) or reply.get('status') != 'ok':
        message = reply.get('message') if isinstance(reply, dict) else ''
        return False, f'FlareSolverr could not load the page: {message or "no reason given"}'
    solution = reply.get('solution') or {}
    status = solution.get('status')
    body = (solution.get('response') or '')
    low = body[:6000].lower()
    if status != 200 or any(marker in low for marker in CHALLENGE_MARKERS):
        return False, (f'FlareSolverr got HTTP {status}, and the page still looks like a bot challenge. '
                       'It may need an update, or this challenge may need a person; see the browser-cache alternative in the guide.')
    return True, f'Royal Road loaded through FlareSolverr (HTTP 200, {len(body):,} characters). Downloads should work now.'


def _section_bounds(lines, section):
    header = re.compile(r'^\s*\[' + re.escape(section) + r'\]\s*$', re.I)
    any_header = re.compile(r'^\s*\[.+\]\s*$')
    start = next((i for i, line in enumerate(lines) if header.match(line)), None)
    if start is None:
        return None, None
    end = next((i for i in range(start + 1, len(lines)) if any_header.match(lines[i])), len(lines))
    return start, end


def is_enabled(text, section=SECTION):
    lines = (text or '').splitlines()
    start, end = _section_bounds(lines, section)
    if start is None:
        return False
    for line in lines[start + 1:end]:
        m = re.match(r'^\s*' + KEY + r'\s*[:=]\s*(\S+)', line)
        if m:
            return m.group(1).lower() == 'true'
    return False


def enable_in_ini(text, section=SECTION):
    """Turn FlareSolverr on for the site without disturbing the rest of the user's settings. Returns (text, changed)."""
    text = text or ''
    lines = text.splitlines()
    start, end = _section_bounds(lines, section)
    wanted = f'{KEY}:true'
    if start is None:
        block = [f'[{section}]', wanted]
        new = lines + ([''] if lines and lines[-1].strip() else []) + block
    else:
        for i in range(start + 1, end):
            if re.match(r'^\s*' + KEY + r'\s*[:=]', lines[i]):
                if re.match(r'^\s*' + KEY + r'\s*[:=]\s*true\s*$', lines[i], re.I):
                    return text, False
                new = lines[:i] + [wanted] + lines[i + 1:]
                break
        else:
            new = lines[:start + 1] + [wanted] + lines[start + 1:]
    return '\n'.join(new) + '\n', True
