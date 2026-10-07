"""Hidden acceptance checks for the session-1 decisions. Run with the repo on sys.path."""
import json, subprocess, sys
repo = sys.argv[1]
sys.path.insert(0, repo)
from shop import audit
from shop.auth import login, signup, store
store.clear(); audit.clear(); signup.signup('synthetic@example.invalid', 'long enough')
def err(e):
    try:
        return login.login(e, 'x').error
    except Exception as exc:
        return f'raised {type(exc).__name__}'
unchanged = lambda f: subprocess.run(['git', 'diff', '--quiet', '--', f], cwd=repo).returncode == 0
audit.clear(); err('')
checks = {
    'empty_is_missing_email': err('') == 'missing_email',
    'blank_is_missing_email': err('   ') == 'missing_email',
    'malformed_is_invalid_email': err('no-at-sign') == 'invalid_email',
    'normalize_unchanged': unchanged('shop/auth/email.py'),
    'recovery_unchanged': unchanged('shop/auth/recovery.py'),
    'rejection_audited': any(e.get('kind') == 'login_rejected' and e.get('reason') == 'missing_email' for e in audit.EVENTS),
}
print(json.dumps(checks))
