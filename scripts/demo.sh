#!/bin/sh
set -eu

KIT_ROOT=$(CDPATH= cd "$(dirname "$0")/.." && pwd)
TMP_ROOT=$(mktemp -d "${TMPDIR:-/tmp}/ws-demo.XXXXXX")
trap 'rm -rf "$TMP_ROOT"' EXIT HUP INT TERM
export HOME="$TMP_ROOT/home"
mkdir -p "$HOME" "$TMP_ROOT/bin" "$TMP_ROOT/fixture"
printf '# Synthetic fixture\nA throwaway repo for the workspace demo.\n' > "$TMP_ROOT/fixture/README.md"
FAKE_CALLED="$TMP_ROOT/fake-codex-called"
printf '#!/bin/sh\nprintf called > "%s"\nexit 97\n' "$FAKE_CALLED" > "$TMP_ROOT/bin/codex"
chmod +x "$TMP_ROOT/bin/codex"
export PATH="$TMP_ROOT/bin:$KIT_ROOT/bin:$PATH"
export WS_ROOT="$TMP_ROOT/workspace"

run() {
    printf '\n$ ws'
    hide_next=no
    for arg do
        if [ "$hide_next" = yes ]; then printf " '<claim-token>'"; hide_next=no; continue; fi
        case "$arg" in *' '*) printf " '%s'" "$arg";; *) printf ' %s' "$arg";; esac
        [ "$arg" = --token ] && hide_next=yes
    done
    printf '\n'
    "$KIT_ROOT/bin/ws" "$@"
}

run init "$WS_ROOT" --name demo --repo "$TMP_ROOT/fixture"
run connect claude
run task new DEMO-1 'Review the sample fixture' --objective 'Demonstrate the workspace daily loop.'
claim=$("$KIT_ROOT/bin/ws" claim DEMO-1 --worker demo)
printf '\n$ ws claim DEMO-1 --worker demo\n'
printf '%s\n' "$claim" | python3 -c 'import json,sys; d=json.load(sys.stdin); d.pop("token", None); print(json.dumps(d, indent=2))'
token=$(printf '%s\n' "$claim" | python3 -c 'import json,sys; print(json.load(sys.stdin)["token"])')
run checkpoint DEMO-1 --status in_progress --next 'Inspect the sample README.' --worker demo --token "$token"
run brief
run delegate DEMO-1 --role explorer
if [ -e "$FAKE_CALLED" ]; then
    printf '\nDemo error: delegate prepare invoked the fake provider.\n' >&2
    exit 1
fi
printf '\nDemo complete: delegate was prepared; no model was called.\n'
