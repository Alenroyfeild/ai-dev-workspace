# Video lessons

## Rendering

Before recording, the maintainer supplies an isolated released-package venv:
`python3 -m venv /tmp/video-venv`, then
`/tmp/video-venv/bin/python -m pip install ai-dev-workspace==0.1.0b5`.
The renderer never installs anything. Use `--ws-python /tmp/video-venv/bin/python`:

```sh
python3 bin/make-video --check
python3 bin/make-video --ws-python /tmp/video-venv/bin/python
```

Clips are not rendered yet: the VHS browser failed to start in the sandbox.
The maintainer renders locally after landing; encoding and visual layout remain unverified.
