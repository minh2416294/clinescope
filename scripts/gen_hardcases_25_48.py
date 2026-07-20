"""One-shot authoring generator for gold hard-cases dm-hc-25..dm-hc-48 (P3a).

NOT shipped/imported by the package -- a throwaway authoring tool. It emits 24 new
World-A v1 traces under examples/gold/ from explicit specs, each a real
`*** Begin Patch` apply_patch built by ONE code path so the grammar is uniform. It
writes ONLY the trace JSON (never a gold label -- labels are the user's, added blind).

Each spec names its divergence KIND (the proxy blind-spot / caught bucket it targets),
carried into the trace `sessionId` for traceability, but NOT into the gold `notes`
(the notes are authored separately, label-free, so a blind labeler never sees intent).

Run: python scripts/gen_hardcases_25_48.py   (from the repo root)
"""

from __future__ import annotations

import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
GOLD_DIR = REPO_ROOT / "examples" / "gold"


def _trace(
    session_id: str, task: str, path: str, before: str, patch_body: str
) -> dict[str, object]:
    """Build a World-A v1 trace: user task -> read_files -> apply_patch(+result)."""
    patch = f"*** Begin Patch\n{patch_body}\n*** End Patch"
    return {
        "version": 1,
        "sessionId": session_id,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": task}]},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "read_files",
                        "input": {"path": path},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-1",
                        "content": before,
                        "is_error": False,
                    }
                ],
            },
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-2",
                        "name": "apply_patch",
                        "input": {"input": patch},
                    }
                ],
            },
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": "call-2",
                        "content": f"Successfully applied patch to the following files:\n{path}",
                        "is_error": False,
                    }
                ],
            },
        ],
    }


# Each entry: (slug, kind, task, file_path, before_content, patch_body).
# patch_body is the lines BETWEEN "*** Begin Patch" and "*** End Patch".
# Kinds (mirroring dm-hc-01..24):
#   under-floor      : delete-run & add-run each < FLOOR=3 (proxy 1.0)
#   interleaved      : strict -,+,-,+ churn, no run reaches 3 (proxy 1.0)
#   tight-surgical   : a genuinely minimal edit (proxy 1.0, human likely NOT-WASTEFUL)
#   context-drag     : one real change dragging many context lines (proxy 1.0)
#   anchor-broken    : a long rewrite split by one surviving context line (proxy 1.0)
#   caught-rewrite   : >=3 consecutive '-' then >=3 consecutive '+' (proxy < 1.0)
SPECS: list[tuple[str, str, str, str, str, str]] = [
    # ---- under-floor (2 new): 2-line delete then 2-line retype -------------------
    (
        "dm-hardcase-25-py-retype-two-thresholds",
        "under-floor",
        "Raise the two alert thresholds in monitor.py.",
        "src/monitor.py",
        "WARN_PCT = 70\nCRIT_PCT = 85\nWINDOW = 60\n",
        "*** Update File: src/monitor.py\n@@\n-WARN_PCT = 70\n-CRIT_PCT = 85\n+WARN_PCT = 80\n+CRIT_PCT = 95\n WINDOW = 60",
    ),
    (
        "dm-hardcase-26-ts-retype-two-flags",
        "under-floor",
        "Flip the two feature flags in config.ts.",
        "web/config.ts",
        "export const flags = {\n  beta: false,\n  legacy: true,\n};\n",
        "*** Update File: web/config.ts\n@@ export const flags = {\n-  beta: false,\n-  legacy: true,\n+  beta: true,\n+  legacy: false,\n };",
    ),
    # ---- interleaved churn (2 new): strict -,+ alternation -----------------------
    (
        "dm-hardcase-27-py-interleaved-defaults",
        "interleaved",
        "Update the three default settings in defaults.py.",
        "src/defaults.py",
        "RETRIES = 1\nTIMEOUT = 5\nBACKOFF = 1.0\nDEBUG = False\n",
        "*** Update File: src/defaults.py\n@@\n-RETRIES = 1\n+RETRIES = 3\n-TIMEOUT = 5\n+TIMEOUT = 30\n-BACKOFF = 1.0\n+BACKOFF = 2.0\n DEBUG = False",
    ),
    (
        "dm-hardcase-28-go-interleaved-consts",
        "interleaved",
        "Bump the three pool constants in pool.go.",
        "internal/pool/pool.go",
        "const (\n\tMinConns = 1\n\tMaxConns = 8\n\tIdleSec  = 30\n)\n",
        "*** Update File: internal/pool/pool.go\n@@ const (\n-\tMinConns = 1\n+\tMinConns = 2\n-\tMaxConns = 8\n+\tMaxConns = 16\n-\tIdleSec  = 30\n+\tIdleSec  = 60\n )",
    ),
    # ---- tight-surgical (4 new): a genuinely minimal edit -----------------------
    (
        "dm-hardcase-29-fix-single-return",
        "tight-surgical",
        "Return the sum instead of the difference in add().",
        "src/calc.py",
        "def add(a, b):\n    return a - b\n",
        "*** Update File: src/calc.py\n@@ def add(a, b):\n-    return a - b\n+    return a + b",
    ),
    (
        "dm-hardcase-30-add-one-import",
        "tight-surgical",
        "Add the missing logging import at the top of app.py.",
        "src/app.py",
        "import os\nimport sys\n\n\ndef main():\n    pass\n",
        "*** Update File: src/app.py\n@@\n import os\n import sys\n+import logging",
    ),
    (
        "dm-hardcase-31-bump-single-version",
        "tight-surgical",
        "Bump the package version to 2.1.0.",
        "pyproject.toml",
        '[project]\nname = "widget"\nversion = "2.0.0"\n',
        '*** Update File: pyproject.toml\n@@ [project]\n name = "widget"\n-version = "2.0.0"\n+version = "2.1.0"',
    ),
    (
        "dm-hardcase-32-add-newline-eof",
        "tight-surgical",
        "Append a trailing constant to settings.py.",
        "src/settings.py",
        "HOST = 'localhost'\nPORT = 8080\n",
        "*** Update File: src/settings.py\n@@\n HOST = 'localhost'\n PORT = 8080\n+TIMEOUT = 30",
    ),
    # ---- context-drag (4 new): one real change, lots of context -----------------
    (
        "dm-hardcase-33-py-timeout-in-big-block",
        "context-drag",
        "Change the default connect timeout to 30 in client.py.",
        "src/client.py",
        "def make_client():\n    opts = {}\n    opts['host'] = 'db'\n    opts['port'] = 5432\n    opts['user'] = 'svc'\n    opts['pool'] = 10\n    opts['timeout'] = 5\n    opts['retries'] = 3\n    return connect(opts)\n",
        "*** Update File: src/client.py\n@@ def make_client():\n     opts = {}\n     opts['host'] = 'db'\n     opts['port'] = 5432\n     opts['user'] = 'svc'\n     opts['pool'] = 10\n-    opts['timeout'] = 5\n+    opts['timeout'] = 30\n     opts['retries'] = 3\n     return connect(opts)",
    ),
    (
        "dm-hardcase-34-yaml-image-in-pod",
        "context-drag",
        "Bump the api image tag to v2 in the deployment.",
        "deploy/api.yaml",
        "spec:\n  containers:\n    - name: api\n      image: api:v1\n      ports:\n        - containerPort: 8080\n      resources:\n        limits:\n          cpu: '1'\n          memory: 256Mi\n",
        "*** Update File: deploy/api.yaml\n@@ spec:\n   containers:\n     - name: api\n-      image: api:v1\n+      image: api:v2\n       ports:\n         - containerPort: 8080\n       resources:\n         limits:\n           cpu: '1'\n           memory: 256Mi",
    ),
    (
        "dm-hardcase-35-go-one-field-in-struct",
        "context-drag",
        "Change the default MaxRetries to 5 in the config literal.",
        "internal/config/config.go",
        'cfg := Config{\n\tHost:       "db",\n\tPort:       5432,\n\tUser:       "svc",\n\tPoolSize:   10,\n\tMaxRetries: 3,\n\tTimeout:    5,\n\tVerbose:    false,\n}\n',
        '*** Update File: internal/config/config.go\n@@ cfg := Config{\n \tHost:       "db",\n \tPort:       5432,\n \tUser:       "svc",\n \tPoolSize:   10,\n-\tMaxRetries: 3,\n+\tMaxRetries: 5,\n \tTimeout:    5,\n \tVerbose:    false,\n }',
    ),
    (
        "dm-hardcase-36-js-one-option-in-object",
        "context-drag",
        "Enable credentials in the fetch options object.",
        "web/src/api.js",
        "const options = {\n  method: 'POST',\n  headers: { 'Content-Type': 'application/json' },\n  cache: 'no-store',\n  credentials: 'omit',\n  redirect: 'follow',\n  keepalive: true,\n};\n",
        "*** Update File: web/src/api.js\n@@ const options = {\n   method: 'POST',\n   headers: { 'Content-Type': 'application/json' },\n   cache: 'no-store',\n-  credentials: 'omit',\n+  credentials: 'include',\n   redirect: 'follow',\n   keepalive: true,\n };",
    ),
    # ---- anchor-broken (4 new): long rewrite split by one context line ----------
    (
        "dm-hardcase-37-py-split-compute",
        "anchor-broken",
        "Rewrite the score computation in rank.py to use weights.",
        "src/rank.py",
        "def rank(items):\n    base = sum(items)\n    n = len(items)\n    avg = base / n\n    scale = 1.0\n    return avg * scale\n",
        "*** Update File: src/rank.py\n@@ def rank(items):\n-    base = sum(items)\n-    n = len(items)\n-    avg = base / n\n     scale = 1.0\n+    total = sum(w * x for w, x in items)\n+    weight = sum(w for w, _ in items)\n+    avg = total / weight\n     return avg * scale",
    ),
    (
        "dm-hardcase-38-go-split-parse",
        "anchor-broken",
        "Rewrite the flag parsing block in main.go.",
        "cmd/main.go",
        'func parse() Opts {\n\thost := flag.String("host", "", "")\n\tport := flag.Int("port", 0, "")\n\tuser := flag.String("user", "", "")\n\tflag.Parse()\n\treturn Opts{Host: *host, Port: *port, User: *user}\n}\n',
        '*** Update File: cmd/main.go\n@@ func parse() Opts {\n-\thost := flag.String("host", "", "")\n-\tport := flag.Int("port", 0, "")\n-\tuser := flag.String("user", "", "")\n \tflag.Parse()\n+\th := flag.String("host", "localhost", "db host")\n+\tp := flag.Int("port", 5432, "db port")\n+\tu := flag.String("user", "svc", "db user")\n \treturn Opts{Host: *host, Port: *port, User: *user}\n }',
    ),
    (
        "dm-hardcase-39-js-split-reducer",
        "anchor-broken",
        "Rewrite the totals computation in the reducer.",
        "web/src/store.js",
        "case 'sum': {\n  const items = state.items;\n  const price = items.reduce((a, i) => a + i.price, 0);\n  const tax = price * 0.1;\n  const shipping = 5;\n  return { ...state, total: price + tax + shipping };\n}\n",
        "*** Update File: web/src/store.js\n@@ case 'sum': {\n-  const items = state.items;\n-  const price = items.reduce((a, i) => a + i.price, 0);\n-  const tax = price * 0.1;\n   const shipping = 5;\n+  const lines = state.items;\n+  const subtotal = lines.reduce((a, i) => a + i.price * i.qty, 0);\n+  const tax = subtotal * 0.08;\n   return { ...state, total: price + tax + shipping };\n }",
    ),
    (
        "dm-hardcase-40-py-split-validate",
        "anchor-broken",
        "Rewrite the validation branch in forms.py.",
        "src/forms.py",
        "def validate(v):\n    if v is None:\n        raise Error('null')\n    if v == '':\n        raise Error('empty')\n    log('ok')\n    return v.strip()\n",
        "*** Update File: src/forms.py\n@@ def validate(v):\n-    if v is None:\n-        raise Error('null')\n-    if v == '':\n-        raise Error('empty')\n     log('ok')\n+    if not v:\n+        raise Error('missing value')\n+    if len(v) > 255:\n+        raise Error('too long')\n     return v.strip()",
    ),
    # ---- caught blind-rewrites (4 new): proxy MUST flag these (< 1.0) -----------
    (
        "dm-hardcase-41-blind-retype-py-config-block",
        "caught-rewrite",
        "Update the four cache settings in cache.py.",
        "src/cache.py",
        "CACHE = {\n    'backend': 'memory',\n    'ttl': 60,\n    'max_entries': 1000,\n    'evict': 'lru',\n}\n",
        "*** Update File: src/cache.py\n@@ CACHE = {\n-    'backend': 'memory',\n-    'ttl': 60,\n-    'max_entries': 1000,\n-    'evict': 'lru',\n+    'backend': 'redis',\n+    'ttl': 300,\n+    'max_entries': 5000,\n+    'evict': 'lfu',\n }",
    ),
    (
        "dm-hardcase-42-blind-retype-go-struct-literal",
        "caught-rewrite",
        "Rewrite the server defaults struct in server.go.",
        "internal/server/server.go",
        'defaults := Settings{\n\tAddr:    ":8080",\n\tTLS:     false,\n\tTimeout: 5,\n\tMaxBody: 1048576,\n\tGzip:    false,\n}\n',
        '*** Update File: internal/server/server.go\n@@ defaults := Settings{\n-\tAddr:    ":8080",\n-\tTLS:     false,\n-\tTimeout: 5,\n-\tMaxBody: 1048576,\n-\tGzip:    false,\n+\tAddr:    ":443",\n+\tTLS:     true,\n+\tTimeout: 30,\n+\tMaxBody: 4194304,\n+\tGzip:    true,\n }',
    ),
    (
        "dm-hardcase-43-blind-retype-yaml-service",
        "caught-rewrite",
        "Rewrite the service ports and env in the compose file.",
        "docker-compose.yaml",
        "services:\n  web:\n    image: web:1\n    ports:\n      - '3000:3000'\n    environment:\n      - NODE_ENV=development\n      - LOG_LEVEL=debug\n      - WORKERS=1\n",
        "*** Update File: docker-compose.yaml\n@@ services:\n   web:\n-    image: web:1\n-    ports:\n-      - '3000:3000'\n-    environment:\n-      - NODE_ENV=development\n-      - LOG_LEVEL=debug\n-      - WORKERS=1\n+    image: web:2\n+    ports:\n+      - '80:3000'\n+    environment:\n+      - NODE_ENV=production\n+      - LOG_LEVEL=info\n+      - WORKERS=4",
    ),
    (
        "dm-hardcase-44-blind-retype-js-handlers",
        "caught-rewrite",
        "Rewrite the three route handlers in routes.js.",
        "web/src/routes.js",
        "const routes = {\n  home: () => render('home'),\n  about: () => render('about'),\n  help: () => render('help'),\n};\n",
        "*** Update File: web/src/routes.js\n@@ const routes = {\n-  home: () => render('home'),\n-  about: () => render('about'),\n-  help: () => render('help'),\n+  home: () => render('landing'),\n+  about: () => render('company'),\n+  help: () => render('support'),\n };",
    ),
    # ---- extra under-floor / tight to reach 24 with a balanced surface ----------
    (
        "dm-hardcase-45-py-retype-pair-limits",
        "under-floor",
        "Adjust the two rate-limit values in limits.py.",
        "src/limits.py",
        "PER_MIN = 60\nPER_HOUR = 1000\nBURST = 10\n",
        "*** Update File: src/limits.py\n@@\n-PER_MIN = 60\n-PER_HOUR = 1000\n+PER_MIN = 120\n+PER_HOUR = 5000\n BURST = 10",
    ),
    (
        "dm-hardcase-46-go-interleaved-two",
        "interleaved",
        "Update the two timeouts in http.go.",
        "internal/http/http.go",
        "\tReadTimeout = 5\n\tWriteTimeout = 5\n\tIdleTimeout = 60\n",
        "*** Update File: internal/http/http.go\n@@\n-\tReadTimeout = 5\n+\tReadTimeout = 15\n-\tWriteTimeout = 5\n+\tWriteTimeout = 15\n \tIdleTimeout = 60",
    ),
    (
        "dm-hardcase-47-context-drag-py-single",
        "context-drag",
        "Turn on strict mode in the parser options.",
        "src/parser.py",
        "OPTS = dict(\n    encoding='utf-8',\n    errors='replace',\n    comments=True,\n    strict=False,\n    trim=True,\n    depth=64,\n)\n",
        "*** Update File: src/parser.py\n@@ OPTS = dict(\n     encoding='utf-8',\n     errors='replace',\n     comments=True,\n-    strict=False,\n+    strict=True,\n     trim=True,\n     depth=64,\n )",
    ),
    (
        "dm-hardcase-48-tight-add-guard-js",
        "tight-surgical",
        "Add an early return for the empty-array case.",
        "web/src/util.js",
        "function firstOr(arr, dflt) {\n  return arr[0];\n}\n",
        "*** Update File: web/src/util.js\n@@ function firstOr(arr, dflt) {\n+  if (arr.length === 0) return dflt;\n   return arr[0];\n }",
    ),
]


def main() -> int:
    if len(SPECS) != 24:
        raise SystemExit(f"expected 24 specs, have {len(SPECS)}")
    GOLD_DIR.mkdir(parents=True, exist_ok=True)
    written = []
    for slug, kind, task, path, before, patch_body in SPECS:
        session_id = slug.replace("dm-hardcase-", "dm-hc-") + f"|{kind}"
        trace = _trace(session_id, task, path, before, patch_body)
        out = GOLD_DIR / f"{slug}.json"
        # LF-only, trailing newline -- matches .gitattributes *.json eol=lf and the
        # existing trace files (pretty 2-space, ensure_ascii keeps it ASCII).
        text = json.dumps(trace, indent=2, ensure_ascii=True) + "\n"
        out.write_bytes(text.encode("utf-8"))
        written.append(out.name)
    print(f"wrote {len(written)} traces to {GOLD_DIR}")
    for name in written:
        print(f"  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
