"""Build the CLI with its checkout resources inside the installed ws package."""
import json
import shutil
from pathlib import Path

from setuptools import setup
from setuptools.command.build_py import build_py

ROOT = Path(__file__).resolve().parent


def kit_files():
    for name in ('template', 'packs', 'skills', 'mcp', 'bin', 'docs', 'kit.json', 'LICENSE'):
        source = ROOT / name
        for path in source.rglob('*') if source.is_dir() else (source,):
            if path.is_file() and not ({'runtime', '__pycache__', '.git'} & set(path.relative_to(ROOT).parts)):
                if path.suffix != '.pyc' and path.name != '.DS_Store':
                    yield path.relative_to(ROOT)


class BuildKit(build_py):
    def run(self):
        super().run()
        for relative in kit_files():
            target = Path(self.build_lib) / 'ws' / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / relative, target)

    def get_outputs(self, include_bytecode=1):
        return super().get_outputs(include_bytecode) + [str(Path(self.build_lib) / 'ws' / p) for p in kit_files()]

    def get_source_files(self):
        return super().get_source_files() + [str(p) for p in kit_files()]


setup(name='ai-dev-workspace', version=json.loads((ROOT / 'kit.json').read_text())['version'],
      description='Durable task memory and coordination for AI-assisted development',
      packages=['ws'], python_requires='>=3.9',
      entry_points={'console_scripts': ['ws=ws.cli:main']}, cmdclass={'build_py': BuildKit})
