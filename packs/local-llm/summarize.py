#!/usr/bin/env python3
"""Summarise a big log with a local Ollama model, after the free deterministic digest.

Usage: summarize.py <file> [--model qwen3.5:4b]. The model sees only the digest (problem lines),
never the whole file, and its answer must quote lines that exist in the file or it is rejected.
"""
import argparse, json, sys, urllib.request
from pathlib import Path
kit = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(kit.parent if (kit / 'core.py').is_file() else kit))
from ws import core

HOST = 'http://127.0.0.1:11434'

def main():
    p = argparse.ArgumentParser(); p.add_argument('file'); p.add_argument('--model', default='qwen3.5:4b'); a = p.parse_args()
    try:
        models = [m['name'] for m in json.load(urllib.request.urlopen(HOST + '/api/tags', timeout=3))['models']]
    except OSError:
        sys.exit('Ollama is not running. Start it: `ollama serve` (install: brew install ollama). Falling back: run `ws digest` instead.')
    if a.model not in models:
        sys.exit(f'Model {a.model} not installed. Run: ollama pull {a.model}')
    d = core.digest_file(a.file)
    prompt = ('Group these build/log problem lines by root cause. For each group give one line: cause, then the exact '
              'line it comes from (copied verbatim). Most important first. Lines:\n' + '\n'.join(d.get('problems', [])))
    body = json.dumps({'model': a.model, 'prompt': prompt, 'stream': False, 'think': False,
                       'options': {'temperature': 0, 'num_ctx': 4096}}).encode()
    req = urllib.request.Request(HOST + '/api/generate', body, {'Content-Type': 'application/json'})
    answer = json.load(urllib.request.urlopen(req, timeout=180))['response']
    source = Path(a.file).read_text(errors='replace')
    quoted = [l for l in answer.splitlines() if len(l.strip()) > 20]
    unverified = [l for l in quoted if not any(chunk in source for chunk in [l.strip()[-40:], l.strip()[:40]])]
    print(answer.strip())
    if unverified and len(unverified) == len(quoted):
        print('\n[local-llm] WARNING: no line of this answer matches the log; trust `ws digest` instead.', file=sys.stderr)

if __name__ == '__main__':
    main()
