"""Extra issue-bound filtering, never applied to local notes or generic redact."""
import re

from . import core

_TOKEN = re.compile(r'(?<!\w)(?:(?:lin_api_|ntn_|secret_)[A-Za-z0-9_-]{40,}|(?:ya29\.|pypi-)[A-Za-z0-9._-]{20,})')
_GROUP_SEPARATORS = ' -.\t\u00a0/_'
_GROUP_GAP = re.compile('[' + re.escape(_GROUP_SEPARATORS) + ']+')
_DIGITS = re.compile(r'[0-9]+')
_CARD_SHAPES = {(4, 4, 4, 4), (4, 4, 4, 4, 3), (4, 6, 5), (4, 6, 4)}
_IBAN = re.compile(r'(?<!\w)[A-Za-z]{2}[0-9]{2}')
_ACCOUNT = re.compile(r'(?<![\w.+-])[0-9]{9,18}(?!\w)(?![.-]\w)')
_URL = re.compile(r'\b[A-Za-z][A-Za-z0-9+.-]*://[^\s<>]+')


def _luhn(value):
    digits = [int(c) for c in value if c.isdigit()]
    return sum((d * 2 - 9 if d > 4 else d * 2) if i % 2 else d
               for i, d in enumerate(reversed(digits))) % 10 == 0


def _card_spans(text):
    groups = list(_DIGITS.finditer(text))
    for index, first in enumerate(groups):
        start = first.start()
        if start and text[start - 1].isalnum():
            continue
        digits, end = first[0], first.end()
        if 13 <= len(digits) <= 19 and (end == len(text) or not text[end].isalnum()) and _luhn(digits):
            yield start, end, len(digits)
        if len(digits) != 4:
            continue
        lengths, separator, candidate = (4,), None, None
        for group in groups[index + 1:index + 5]:
            if group.start() == end or not _GROUP_GAP.fullmatch(text, end, group.start()):
                break
            gap = text[end:group.start()]
            if separator is not None and gap != separator:
                break
            separator = gap
            group_length = group.end() - group.start()
            if group_length > 6:
                break
            lengths += (group_length,)
            digits += group[0]
            end = group.end()
            if lengths in _CARD_SHAPES and (end == len(text) or not text[end].isalnum()) and _luhn(digits):
                candidate = start, end, len(digits)
        if candidate is not None:
            yield candidate


def _cards(text):
    spans = []
    for start, end, length in _card_spans(text):
        if spans and start < spans[-1][1]:
            first, last, longest = spans[-1]
            # A shorter window through the same card can include an adjacent
            # numeric field. Equal or longer overlaps extend the redaction.
            if length >= longest:
                spans[-1] = (first, max(last, end), length)
        else:
            spans.append((start, end, length))
    parts, cursor = [], 0
    for start, end, _ in spans:
        parts.extend((text[cursor:start], '[REDACTED]'))
        cursor = end
    return ''.join(parts) + text[cursor:]


def _mod97(value):
    remainder = 0
    for char in value[4:] + value[:4]:
        remainder = (remainder * (10 if char.isdigit() else 100) +
                     (int(char) if char.isdigit() else ord(char) - 55)) % 97
    return remainder == 1


def _ibans(text):
    parts, cursor = [], 0
    for match in _IBAN.finditer(text):
        if match.start() < cursor: continue
        value, end, pos = '', None, match.start()
        # At most 34 alphanumeric characters; separators do not count toward IBAN length.
        while pos < len(text) and len(value) < 34:
            char = text[pos]
            if char in _GROUP_SEPARATORS: pos += 1; continue
            if not (char.isascii() and char.isalnum()): break
            value += char.upper()
            pos += 1
            if len(value) >= 15 and (pos == len(text) or not text[pos].isalnum()) and _mod97(value):
                end = pos
        if end is not None:
            parts.extend((text[cursor:match.start()], '[REDACTED]'))
            cursor = end
    return ''.join(parts) + text[cursor:]


def issue_text(text):
    """Redact before title truncation and before either external submission route.

    Token heuristics require 40 suffix characters for Linear/Notion, 20 for
    Google/PyPI. Checksums do not prove an identifier is real; preview is required.
    """
    text = _TOKEN.sub('[REDACTED]', core.redact(text))
    text = _ibans(text)
    text = _cards(text)
    # Account heuristics must not remove numeric URL paths; query values still count.
    parts, cursor = [], 0
    for match in _URL.finditer(text):
        parts.append(_ACCOUNT.sub('[REDACTED]', text[cursor:match.start()]))
        url = match[0]
        boundary = min([url.find(c) for c in ('?', '#') if c in url] or [len(url)])
        path = url.find('/', url.index('://') + 3)
        if 0 <= path < boundary:
            parts.extend((_ACCOUNT.sub('[REDACTED]', url[:path]), url[path:boundary],
                          _ACCOUNT.sub('[REDACTED]', url[boundary:])))
        else:
            parts.append(_ACCOUNT.sub('[REDACTED]', url))
        cursor = match.end()
    return ''.join(parts) + _ACCOUNT.sub('[REDACTED]', text[cursor:])
