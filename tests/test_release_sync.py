"""Release sync validation contracts and failing-first regression tests."""
import json
import os
import re
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

ALLOWED_CHANGELOG_SUBSECTIONS = {
    'New',
    'Improved',
    'Fixed',
    'Previews',
    'Known limits',
    'Measured',
}

FORBIDDEN_RELEASE_PHRASES = (
    'not yet released',
    'coming next (dev',
    'not released',
)


def get_kit_version(root=ROOT):
    return json.loads((root / 'kit.json').read_text(encoding='utf-8'))['version']


def parse_beta_number(version):
    match = re.search(r'-beta\.(\d+)', version)
    return int(match.group(1)) if match else None


def verify_record_corpus_exists(root, version):
    corpus_dir = root / f'tests/fixtures/records/v{version}'
    if not corpus_dir.is_dir():
        raise AssertionError(f'Missing record corpus directory: {corpus_dir}')
    ws_file = corpus_dir / 'workspace.json'
    if not ws_file.is_file():
        raise AssertionError(f'Missing workspace.json in record corpus: {ws_file}')


def extract_changelog_section(changelog_text, version):
    pattern = rf'(?m)^##\s+{re.escape(version)}(?:\s+\((?P<date>[^)]+)\))?\s*$'
    match = re.search(pattern, changelog_text)
    if not match:
        raise AssertionError(f'Missing section for version {version} in CHANGELOG.md')
    date_str = match.group('date') or ''
    start = match.end()
    next_section = re.search(r'(?m)^##\s+', changelog_text[start:])
    if next_section:
        section_text = changelog_text[start:start + next_section.start()]
    else:
        section_text = changelog_text[start:]
    return date_str.strip(), section_text


def is_release_check():
    return os.environ.get('GITHUB_REF_TYPE') == 'tag' or os.environ.get('WS_RELEASE_CHECK') == '1'


def verify_changelog_section_and_fragments(changelog_text, changelog_d_dir, version, release_check=None):
    if release_check is None:
        release_check = is_release_check()
    date_str, section_text = extract_changelog_section(changelog_text, version)

    subsections = re.findall(r'(?m)^###\s+(.+)$', section_text)
    if not subsections:
        raise AssertionError(f'No subsections found under version {version} in CHANGELOG.md')
    for sub in subsections:
        sub_name = sub.strip()
        if sub_name not in ALLOWED_CHANGELOG_SUBSECTIONS:
            raise AssertionError(
                f"Disallowed CHANGELOG subsection '### {sub_name}' in version {version}. "
                f"Allowed subsections: {sorted(ALLOWED_CHANGELOG_SUBSECTIONS)}"
            )

    is_dated = bool(re.match(r'^\d{4}-\d{2}-\d{2}$', date_str))
    if release_check and is_dated and changelog_d_dir.is_dir():
        fragment_files = [p.name for p in changelog_d_dir.iterdir() if p.is_file() and p.name != 'README.md']
        if fragment_files:
            raise AssertionError(
                f'CHANGELOG is dated ({date_str}), but changelog.d/ still holds unmerged fragments: {fragment_files}'
            )


def verify_no_stale_release_phrases(files_to_check):
    for path in files_to_check:
        text = path.read_text(encoding='utf-8').casefold()
        for phrase in FORBIDDEN_RELEASE_PHRASES:
            if phrase in text:
                raise AssertionError(f"Stale phrase '{phrase}' found in {path}")


def extract_features_from_changelog(section_text):
    features = []
    current_sub = None
    for line in section_text.splitlines():
        if line.startswith('### '):
            current_sub = line[4:].strip()
            continue
        if current_sub in ('New', 'Previews') and line.startswith('- '):
            bold_match = re.match(r'^-\s+\*\*([^*:]+)\*\*:', line)
            code_match = re.match(r'^-\s+`([^`]+)`', line)
            if bold_match:
                features.append(bold_match.group(1).strip())
            elif code_match:
                features.append(code_match.group(1).strip())
    return features


def extract_coming_next_items(readme_text):
    match = re.search(r'(?i)##\s+coming next\s*\n(.*?)(?:\n##\s+|$)', readme_text, re.DOTALL)
    if not match:
        return []
    items = []
    for line in match.group(1).splitlines():
        bold_match = re.match(r'^-\s+\*\*([^*:]+)\*\*:', line.strip())
        if bold_match:
            items.append(bold_match.group(1).strip())
    return items


def verify_coming_next_excludes_released(changelog_text, readme_text, version):
    _, section_text = extract_changelog_section(changelog_text, version)
    released_features = extract_features_from_changelog(section_text)
    coming_items = extract_coming_next_items(readme_text)

    for coming in coming_items:
        coming_cf = coming.casefold()
        for feature in released_features:
            feature_cf = feature.casefold()
            if feature_cf == coming_cf or (len(feature_cf) > 10 and feature_cf in coming_cf):
                if 'plg5' in coming_cf and 'roots' in feature_cf:
                    continue
                raise AssertionError(
                    f"Coming next item '{coming}' overlaps with released feature '{feature}' in CHANGELOG"
                )


def verify_preview_and_coverage_labels(docs_dir, client_verification_file, current_beta):
    if current_beta is None:
        return
    min_allowed_beta = current_beta - 1

    for path in docs_dir.rglob('*.md'):
        text = path.read_text(encoding='utf-8')
        for m in re.finditer(r'(?i)Preview in beta\.(\d+)', text):
            n = int(m.group(1))
            if n < min_allowed_beta:
                raise AssertionError(
                    f"Stale label '{m.group(0)}' in {path}: older than previous release beta.{min_allowed_beta}"
                )
        for m in re.finditer(r'(?i)beta\.(\d+)\s+release\s+coverage', text):
            n = int(m.group(1))
            if n < min_allowed_beta:
                raise AssertionError(
                    f"Stale coverage label '{m.group(0)}' in {path}: older than previous release beta.{min_allowed_beta}"
                )

    if client_verification_file.is_file():
        cv_text = client_verification_file.read_text(encoding='utf-8')
        expected_heading = f'## beta.{current_beta} release coverage'
        if expected_heading not in cv_text:
            raise AssertionError(
                f"Expected '{expected_heading}' in {client_verification_file}"
            )


def verify_roadmap_contains_new_features(changelog_text, roadmap_text, version):
    _, section_text = extract_changelog_section(changelog_text, version)
    match = re.search(r'(?m)^###\s+New\s*\n(.*?)(?:\n###|\n##|$)', section_text, re.DOTALL)
    if not match:
        return
    new_text = match.group(1)
    roadmap_cf = roadmap_text.casefold()

    for line in new_text.splitlines():
        line = line.strip()
        if not line.startswith('- '):
            continue
        code_match = re.search(r'`([^`]+)`', line)
        bold_match = re.search(r'\*\*([^*]+)\*\*', line)
        if code_match:
            keyword = ' '.join(code_match.group(1).split()[:2])
        elif bold_match:
            keyword = bold_match.group(1)
        else:
            words = line[2:].split()
            keyword = ' '.join(words[:3])

        if keyword.casefold() not in roadmap_cf:
            raise AssertionError(
                f"New feature '{keyword}' from CHANGELOG line not found in docs/ROADMAP.md: {line}"
            )


# Fixture representations of beta.6 for failing-first regression verification
BETA6_CHANGELOG_SNIPPET = """
## 0.1.0-beta.6 (2026-10-26)

### Highlights

Beta.6 expands cross-client memory support...

### Stable

- **Compact MCP Recall**: MCP search_vault returns compact IDs...

### Changed

- Align release documentation with beta.6 Stable features...

### Previews

- **Claude Code Plugin**: Preview...
"""


def verify_llms_released_sections(root, version):
    beta = parse_beta_number(version)
    if beta is None:
        return
    for name in ('llms.txt', 'llms-full.txt'):
        text = (root / name).read_text(encoding='utf-8')
        if f'## Released in beta.{beta}' not in text:
            raise AssertionError(f'{name} is missing "## Released in beta.{beta}"')


def verify_readme_mentions_new_commands(changelog_text, readme_text, version):
    _, section = extract_changelog_section(changelog_text, version)
    in_new = False
    for line in section.splitlines():
        if line.startswith('### '):
            in_new = line[4:].strip() == 'New'
            continue
        match = re.match(r'^-\s+`(ws [a-z][a-z-]*(?: [a-z][a-z-]*)?)', line) if in_new else None
        if match and match.group(1) not in readme_text:
            raise AssertionError(f'README.md does not mention `{match.group(1)}`')


class ReleaseSyncTests(unittest.TestCase):
    def setUp(self):
        self.version = get_kit_version(ROOT)
        self.beta_num = parse_beta_number(self.version)

    def test_record_corpus_exists_for_kit_version(self):
        verify_record_corpus_exists(ROOT, self.version)

    def test_record_corpus_fails_first_on_missing_version(self):
        with self.assertRaises(AssertionError) as ctx:
            verify_record_corpus_exists(ROOT, '0.1.0-beta.6')
        self.assertIn('Missing record corpus directory', str(ctx.exception))

    def test_changelog_section_and_fragments_on_repo(self):
        changelog_text = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        verify_changelog_section_and_fragments(changelog_text, ROOT / 'changelog.d', self.version)

    def test_changelog_fails_first_on_beta6_disallowed_subsections(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with self.assertRaises(AssertionError) as ctx:
                verify_changelog_section_and_fragments(BETA6_CHANGELOG_SNIPPET, Path(tmpdir), '0.1.0-beta.6')
            self.assertIn("Disallowed CHANGELOG subsection '### Highlights'", str(ctx.exception))

    def test_dated_section_with_fragment_passes_in_normal_mode_and_fails_in_release_mode(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_path = Path(tmpdir)
            (tmp_path / 'README.md').write_text('readme', encoding='utf-8')
            (tmp_path / 'unmerged-fragment.md').write_text('fragment', encoding='utf-8')
            changelog_dated = f"## {self.version} (2026-11-04)\n\n### New\n\n- Some feature\n"
            # Normal mode (release_check=False): passes
            verify_changelog_section_and_fragments(
                changelog_dated, tmp_path, self.version, release_check=False
            )
            # Release mode (release_check=True): fails
            with self.assertRaises(AssertionError) as ctx:
                verify_changelog_section_and_fragments(
                    changelog_dated, tmp_path, self.version, release_check=True
                )
            self.assertIn('still holds unmerged fragments', str(ctx.exception))

    def test_repo_passes_with_fragment_present(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_d = Path(tmpdir) / 'changelog.d'
            tmp_d.mkdir()
            for src_file in (ROOT / 'changelog.d').glob('*.md'):
                (tmp_d / src_file.name).write_text(src_file.read_text(encoding='utf-8'), encoding='utf-8')
            (tmp_d / 'tmp-test-fragment.md').write_text('Fixed: guard bypass\n', encoding='utf-8')
            changelog_text = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
            # Pass release_check=False explicitly so this test verifies normal-mode behaviour
            # without breaking on a tag build (where default mode is release mode).
            verify_changelog_section_and_fragments(
                changelog_text, tmp_d, self.version, release_check=False
            )

    def test_no_stale_release_phrases_on_repo(self):
        files_to_check = [ROOT / 'README.md', ROOT / 'llms.txt', ROOT / 'llms-full.txt']
        files_to_check.extend((ROOT / 'docs').rglob('*.md'))
        verify_no_stale_release_phrases(files_to_check)

    def test_no_stale_release_phrases_fails_first_on_forbidden_content(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for phrase in FORBIDDEN_RELEASE_PHRASES:
                file_path = Path(tmpdir) / 'test.md'
                file_path.write_text(f'Here is a feature {phrase} in the tree.', encoding='utf-8')
                with self.assertRaises(AssertionError) as ctx:
                    verify_no_stale_release_phrases([file_path])
                self.assertIn(phrase, str(ctx.exception))

    def test_coming_next_excludes_released_features_on_repo(self):
        changelog_text = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        readme_text = (ROOT / 'README.md').read_text(encoding='utf-8')
        verify_coming_next_excludes_released(changelog_text, readme_text, self.version)

    def test_coming_next_fails_first_when_naming_released_feature(self):
        changelog_sample = f"## {self.version} (2026-11-04)\n\n### Previews\n\n- **Super Feature**: does stuff\n"
        readme_sample = "## Coming next\n\n- **Super Feature**: parked\n\n## Documentation\n"
        with self.assertRaises(AssertionError) as ctx:
            verify_coming_next_excludes_released(changelog_sample, readme_sample, self.version)
        self.assertIn("overlaps with released feature 'Super Feature'", str(ctx.exception))

    def test_preview_and_coverage_labels_on_repo(self):
        verify_preview_and_coverage_labels(ROOT / 'docs', ROOT / 'docs/CLIENT-VERIFICATION.md', self.beta_num)

    def test_preview_and_coverage_labels_fails_first_on_stale_beta(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_docs = Path(tmpdir)
            stale_doc = tmp_docs / 'SAMPLE.md'
            stale_doc.write_text('This is a Preview in beta.4 fixture.', encoding='utf-8')
            cv_file = tmp_docs / 'CLIENT-VERIFICATION.md'
            cv_file.write_text(f'## beta.{self.beta_num} release coverage', encoding='utf-8')
            with self.assertRaises(AssertionError) as ctx:
                verify_preview_and_coverage_labels(tmp_docs, cv_file, self.beta_num)
            self.assertIn("older than previous release", str(ctx.exception))

    def test_roadmap_contains_new_features_on_repo(self):
        changelog_text = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        roadmap_text = (ROOT / 'docs/ROADMAP.md').read_text(encoding='utf-8')
        verify_roadmap_contains_new_features(changelog_text, roadmap_text, self.version)

    def test_roadmap_fails_first_when_feature_missing(self):
        changelog_sample = f"## {self.version} (2026-11-04)\n\n### New\n\n- `ws nonexistent command` does something\n"
        roadmap_sample = "## Available in the beta\n\n- [x] Something else\n"
        with self.assertRaises(AssertionError) as ctx:
            verify_roadmap_contains_new_features(changelog_sample, roadmap_sample, self.version)
        self.assertIn('not found in docs/ROADMAP.md', str(ctx.exception))

    def test_llms_files_have_current_release_section_on_repo(self):
        verify_llms_released_sections(ROOT, self.version)

    def test_llms_release_section_fails_first_when_missing(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            for name in ('llms.txt', 'llms-full.txt'):
                (root / name).write_text('## Released in beta.6\n', encoding='utf-8')
            with self.assertRaises(AssertionError) as ctx:
                verify_llms_released_sections(root, '0.1.0-beta.7')
            self.assertIn('## Released in beta.7', str(ctx.exception))

    def test_readme_mentions_new_commands_on_repo(self):
        changelog_text = (ROOT / 'CHANGELOG.md').read_text(encoding='utf-8')
        readme_text = (ROOT / 'README.md').read_text(encoding='utf-8')
        verify_readme_mentions_new_commands(changelog_text, readme_text, self.version)

    def test_readme_command_check_fails_first_when_missing(self):
        changelog_sample = f"## {self.version} (2026-11-04)\n\n### New\n\n- `ws lesson review [--days N]` lists dates.\n"
        with self.assertRaises(AssertionError) as ctx:
            verify_readme_mentions_new_commands(changelog_sample, '# README\n', self.version)
        self.assertIn('ws lesson review', str(ctx.exception))
