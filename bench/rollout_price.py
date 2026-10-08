"""Optional local Codeburn pricing for the disposable rollout benchmark."""
import json
import os
import shutil
import subprocess
import tempfile
import threading
from pathlib import Path


def cost(home):
    """Local Codeburn pricing; the export is a pipe, never a transcript/project data file."""
    if not shutil.which('codeburn'): return None
    with tempfile.TemporaryDirectory(prefix='ws-rollout-price-') as d:
        path = Path(d) / 'usage.json'; os.mkfifo(path); fd = os.open(path, os.O_RDWR | os.O_NONBLOCK)
        chunks = []; finished = threading.Event()
        def drain():
            while True:
                try:
                    data = os.read(fd, 65536)
                    if data: chunks.append(data)
                except BlockingIOError:
                    if finished.is_set(): break
                    finished.wait(.01)
        reader = threading.Thread(target=drain, daemon=True); reader.start()
        try:
            result = subprocess.run(['codeburn', 'export', '-f', 'json', '--provider', 'codex', '-o', str(path)],
                env=dict(os.environ, HOME=str(home), CODEX_HOME=str(home / '.codex')), capture_output=True, timeout=30)
            finished.set(); reader.join()
            data = json.loads(b''.join(chunks))
            rows = data.get('records', [])
            return (sum(r['cost'] for r in rows) or None) if result.returncode == 0 and rows and data['currency']['code'] == 'USD' else None
        except (ValueError, KeyError, subprocess.TimeoutExpired): return None
        finally:
            finished.set(); reader.join(); os.close(fd)
