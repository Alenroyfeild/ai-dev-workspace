"""OpenAI-compatible gateway provider (Preview): one chat-completions request over stdlib urllib.

The API key is read only from the environment variable the routing entry names. It is never stored,
logged, printed or put in a URL, and it is scrubbed from anything this module returns.
"""
import ipaddress
import json
import re
import socket
import urllib.error
import urllib.parse
import urllib.request

from . import core

KIND = 'openai-compatible'
MAX_REPLY = 2_000_000


def parse(settings, environ):
    """Validate one routing entry. Returns (config, problem); problem is '' when usable. No network."""
    try:
        url = urllib.parse.urlsplit(settings.get('base_url'))
        host, port = url.hostname, url.port
    except (ValueError, TypeError, AttributeError):
        return None, 'base_url is not a valid URL.'
    if url.scheme not in ('http', 'https') or not host: return None, 'base_url must be an http:// or https:// URL.'
    if url.username is not None or url.password is not None or url.query or url.fragment:
        return None, 'base_url must not contain credentials, a query or a fragment.'
    env = settings.get('api_key_env')
    if env is not None and (not isinstance(env, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_]{0,63}', env)):
        return None, 'api_key_env must be an environment variable name, never the key itself.'
    try: loopback = ipaddress.ip_address(host).is_loopback
    except ValueError: loopback = host.lower() == 'localhost'
    if env and not loopback and url.scheme != 'https':
        return None, 'A non-loopback gateway with an API key must use https:// (the key would travel in clear text).'
    config = dict(base_url=url.geturl().rstrip('/'), api_key_env=env, loopback=loopback,
                  warning='' if loopback else f'Gateway {host} is not loopback: the redacted task brief is sent to it.')
    if env and not environ.get(env): return config, f'Environment variable {env} is not set.'
    return config, ''


def run(config, model, body, timeout, environ):
    """POST the brief and return worker_run's tuple: (code, text, tokens_in, tokens_out, usage_known)."""
    key = environ.get(config['api_key_env'] or '', '')
    headers = {'Content-Type': 'application/json', 'Accept': 'application/json', 'User-Agent': 'ai-dev-workspace'}
    if key: headers['Authorization'] = 'Bearer ' + key
    request = urllib.request.Request(config['base_url'] + '/chat/completions', method='POST', headers=headers,
                                     data=json.dumps({'model': model, 'messages': [{'role': 'user', 'content': body}]}).encode())

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args, **kwargs): return None  # a redirect must never carry the key elsewhere

    handlers = [NoRedirect()] + ([urllib.request.ProxyHandler({})] if config['loopback'] else [])
    scrub = lambda text: core.redact(text.replace(key, '[REDACTED]') if key else text)  # noqa: E731
    try:
        send = urllib.request.build_opener(*handlers).open  # a network request, not a text-file open
        with send(request, timeout=timeout) as reply:
            raw = reply.read(MAX_REPLY + 1)
        if len(raw) > MAX_REPLY: return 1, 'Gateway reply too large.', 0, 0, False
        data = json.loads(raw.decode('utf-8', errors='replace'))
        text = data['choices'][0]['message']['content']
        usage = data.get('usage') if isinstance(data.get('usage'), dict) else {}
        tokens = [usage.get(name) for name in ('prompt_tokens', 'completion_tokens')]
        known = all(type(count) is int and count >= 0 for count in tokens)
        return 0, scrub(str(text))[:24000], *(tokens if known else (0, 0)), known
    except urllib.error.HTTPError as exc:
        return 1, scrub(f'Gateway returned HTTP {exc.code}.'), 0, 0, False
    except (socket.timeout, TimeoutError):
        return 124, f'Gateway timed out after {timeout} seconds.', 0, 0, False
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, (socket.timeout, TimeoutError)): return 124, f'Gateway timed out after {timeout} seconds.', 0, 0, False
        return 1, 'Gateway could not be reached.', 0, 0, False
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        return 1, 'Gateway reply was not a chat completion.', 0, 0, False
