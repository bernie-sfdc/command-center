#!/usr/bin/env python3
"""
build.py — renders the template into a personal command center.

    python3 build.py --template template/index.html.tmpl \
                     --config  command-center.config.json \
                     --out     index.html

Run by the setup skill after the interview, and again any time the user's
config or the template changes. Rendering is pure text substitution: no
network, no connector calls, no user data leaves the machine.

Validation is deliberately strict. A config that is merely well-formed but
semantically wrong (a made-up Salesforce user id, say) produces an app that
silently returns zero rows, which is the single most confusing failure mode
this tool has. So: fail at build time, loudly, rather than at 8am on a
Monday inside a panel that just looks empty.
"""

import argparse
import json
import os
import re
import sys

SCHEMA = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                      "..", "reference", "config.schema.json")


def schema_errors(cfg):
    """Validate against config.schema.json.

    The hand-rolled checks below cover the values that produce the most
    confusing runtime failures, but they are not the schema. Without this,
    a config could omit user.fullName (schema-required) or misspell coreAes
    and still build: the app then compares your Slack name against undefined
    and shows you your own posts, or renders a permanently empty
    By-core-AE tab. Both look like bugs in the app rather than the config.
    """
    try:
        import jsonschema
    except ImportError:
        return None                      # caller warns
    try:
        schema = json.load(open(SCHEMA, encoding="utf-8"))
    except OSError:
        return None
    v = jsonschema.Draft7Validator(schema)
    return [f"{'.'.join(str(p) for p in e.path) or '(root)'}: {e.message}"
            for e in sorted(v.iter_errors(cfg), key=lambda e: list(e.path))]

REQUIRED_TOOLS = ["sfRead"]          # without Salesforce there is no app
OPTIONAL_TOOLS = [
    "sfWrite", "driveSearch", "slackSearchPublic", "slackSearchAll",
    "gmailSearch", "gmailCreateDraft", "gmailUnlabelThread",
    "gmailLabelThread", "calendarList",
]
SF_ID = re.compile(r"^[0-9A-Za-z]{15}([0-9A-Za-z]{3})?$")
TOOL_NAME = re.compile(r"^mcp__[\w.-]+__\w+$")


def fail(msg):
    sys.exit(f"build failed: {msg}")


def validate(cfg):
    errs, warns = [], []

    user = cfg.get("user") or {}
    if not user.get("email"):
        errs.append("user.email is required")
    if not SF_ID.match(str(user.get("sfUserId", ""))):
        errs.append(
            "user.sfUserId must be a 15 or 18 character Salesforce id. "
            "Do not guess it — read it from the running org "
            "(SELECT Id FROM User WHERE Username = '<your username>'). "
            "A wrong id returns 0 rows from every query."
        )
    if not user.get("slackUserId"):
        warns.append("user.slackUserId missing — the Slack DM panel stays empty")

    tools = cfg.get("tools") or {}
    for t in REQUIRED_TOOLS:
        if not tools.get(t):
            errs.append(f"tools.{t} is required")
    for name, val in tools.items():
        if val and not TOOL_NAME.match(str(val)):
            errs.append(f"tools.{name} is not a connector tool name: {val!r}")
    for t in OPTIONAL_TOOLS:
        if not tools.get(t):
            warns.append(f"tools.{t} missing — dependent panels degrade")
    tools.setdefault("sfWrite", None)
    for t in OPTIONAL_TOOLS:
        tools.setdefault(t, None)

    for i, f in enumerate(cfg.get("families") or []):
        for k in ("slug", "disp", "re"):
            if not f.get(k):
                errs.append(f"families[{i}].{k} is required")
        try:
            re.compile(f.get("re", ""))
        except re.error as e:
            errs.append(f"families[{i}].re is not a valid regex: {e}")

    if not cfg.get("families"):
        warns.append(
            "families is empty — the app will derive the book from "
            "AccountTeamMember at first load, which is usually what you want"
        )

    cfg.setdefault("sf", {}).setdefault("apiVersion", "v66.0")
    cfg.setdefault("slackChannels", [])
    cfg.setdefault("hpfSnapshot", None)
    return errs, warns


def js_regex_safe(cfg):
    """JS RegExp has no re.X/re.S; flag them early rather than at runtime."""
    out = []
    for f in cfg.get("families") or []:
        flags = f.get("reFlags", "i")
        bad = set(flags) - set("gimsuy")
        if bad:
            out.append(f"families[{f.get('slug')}].reFlags has "
                       f"non-JS flags: {''.join(sorted(bad))}")
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--template", required=True)
    ap.add_argument("--config", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--pov", help="optional POV data JSON (stays local)")
    ap.add_argument("--linkedin", help="optional LinkedIn data JSON (stays local)")
    args = ap.parse_args()

    try:
        cfg = json.load(open(args.config, encoding="utf-8"))
    except json.JSONDecodeError as e:
        fail(f"{args.config} is not valid JSON: {e}")

    errs, warns = validate(cfg)
    errs += js_regex_safe(cfg)

    se = schema_errors(cfg)
    if se is None:
        warns.append("jsonschema not installed — schema not enforced, only the "
                     "built-in checks ran. pip install jsonschema")
    else:
        errs += se

    # firstName is schema-optional but used unguarded in the sign-off line,
    # where a missing value renders a literal empty pair of quotes.
    user = cfg.setdefault("user", {})
    if not user.get("firstName") and user.get("fullName"):
        user["firstName"] = user["fullName"].split(" ")[0]

    if errs:
        print("Configuration problems:", file=sys.stderr)
        for e in errs:
            print(f"  - {e}", file=sys.stderr)
        sys.exit(1)
    for w in warns:
        print(f"  note: {w}")

    tmpl = open(args.template, encoding="utf-8").read()

    def load_blob(path, default):
        if not path:
            return default
        raw = open(path, encoding="utf-8").read().strip()
        json.loads(raw)                      # validate before embedding
        return "'" + raw.replace("\\", "\\\\").replace("'", "\\'") \
                        .replace("\n", "\\n") + "'"

    # The config is injected inside a <script> block, so "</script>" anywhere
    # in a config string would close it early and dump the rest as page text.
    # Escaping the sequence is the standard fix and is invisible to JSON.parse.
    cfg_json = (json.dumps(cfg, indent=2, ensure_ascii=False)
                .replace("</", "<\\/")
                .replace("\u2028", "\\u2028").replace("\u2029", "\\u2029"))

    def html_escape(s):
        return (str(s).replace("&", "&amp;").replace("<", "&lt;")
                .replace(">", "&gt;").replace('"', "&quot;"))

    mgr_first = (cfg.get("user", {}).get("managerFirst")
                 or cfg.get("user", {}).get("managerName", "").split(" ")[0]
                 or "my manager")

    subs = {
        "{{CC_CONFIG_JSON}}": cfg_json,
        "{{POV_DATA_JSON}}": load_blob(args.pov, "'{\"_meta\":{}}'"),
        "{{LINKEDIN_DATA_JSON}}": load_blob(args.linkedin, "'[]'"),
        # Lands in an <option> element, so it is HTML-escaped, not JS-escaped.
        "{{MANAGER_FIRST}}": html_escape(mgr_first),
    }
    for k, v in subs.items():
        tmpl = tmpl.replace(k, v)

    # Mixed case too: a {{Token}} that this regex misses would render the
    # literal braces to the user.
    left = sorted(set(re.findall(r"\{\{[A-Za-z_][A-Za-z_0-9]*\}\}", tmpl)))
    if left:
        fail("unreplaced placeholders remain: " + ", ".join(left))

    open(args.out, "w", encoding="utf-8", newline="\n").write(tmpl)
    print(f"\nwrote {args.out}  ({len(tmpl):,} bytes)")
    if args.pov or args.linkedin:
        print("This build embeds your own account data. Local only: do not "
              "host it, email it, or commit it.")


if __name__ == "__main__":
    main()
