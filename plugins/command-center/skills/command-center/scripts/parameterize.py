#!/usr/bin/env python3
"""
parameterize.py — MAINTAINER TOOL (not run by installers).

Turns a personal ae-command-center HTML artifact into a shareable template by
replacing every install-specific value with a single injection point.

    python3 parameterize.py SOURCE.html -o template/index.html.tmpl

Design note
-----------
Rather than sprinkle 20 placeholders through 9,000 lines, this collapses all
personalization into ONE placeholder, {{CC_CONFIG_JSON}}, holding a config
object. The existing constants (SF, ME, ME_ID, FAMILIES, ...) are rewired to
read from it, so the rest of the app is untouched and stays diffable against
the original.

Re-run this against the newest artifact whenever the app changes. That is the
whole point: the template is a build product, never hand-edited.
"""

import argparse
import json
import re
import sys

# ---------------------------------------------------------------------------
# The config object injected at the top of the app's script block.
# ---------------------------------------------------------------------------
CONFIG_BLOCK = """
/* ======================================================================
   INSTALL CONFIG
   Written by the command-center setup skill from command-center.config.json.
   Everything install-specific lives here and nowhere else in this file.

   Connector tool names are NOT portable. The mcp__<uuid>__<tool> strings are
   per-install connector ids, so they are resolved at setup time on the
   machine that will run this app. A missing connector leaves its entry null;
   BRIDGE_GAPS() degrades the affected panels instead of throwing.

   This file contains no customer records as shipped. If POV data is loaded
   below it is the operator's own, and the file becomes as sensitive as that
   data: local only, never hosted, emailed, or committed.
   ====================================================================== */
const CC = {{CC_CONFIG_JSON}};

const SF     = CC.tools.sfRead;
const SFW    = CC.tools.sfWrite;
const DRIVE  = CC.tools.driveSearch;
const SLACK  = CC.tools.slackSearchPublic;
const SLACKP = CC.tools.slackSearchAll;
const GMAIL  = CC.tools.gmailSearch;
const GDRAFT = CC.tools.gmailCreateDraft;
const GUNLAB = CC.tools.gmailUnlabelThread;
const GLABEL = CC.tools.gmailLabelThread;
const CAL    = CC.tools.calendarList;

const ME       = CC.user.email;
const ME_ID    = CC.user.sfUserId;
const SLACK_ME = CC.user.slackUserId;
const APIV     = CC.sf.apiVersion;

const MANAGER_NAME  = CC.user.managerName  || 'my manager';
const MANAGER_FIRST = CC.user.managerFirst || MANAGER_NAME.split(' ')[0];

/* Helpers for the values that used to be hardcoded names. */
function coreAeList(){
  const a = (CC.coreAes || []).map(function(x){ return x.name || x; })
                              .filter(Boolean);
  if(!a.length) return 'the core AEs';
  if(a.length === 1) return a[0];
  return a.slice(0, -1).join(', ') + ' and ' + a[a.length - 1];
}

/* The tagline was static markup naming one person. Filled from config now.
   Not wrapped in DOMContentLoaded alone: this script also runs in builds where
   the listener would attach after the event had already fired. */
function ccFillTagline(){
  const el = document.getElementById('ccTagline');
  if(!el) return;
  el.textContent = [CC.user.fullName, CC.user.roleTitle,
                    CC.user.segmentName, CC.user.levels]
                   .filter(Boolean).join(' \\u00b7 ');
}
if(document.readyState === 'loading')
  document.addEventListener('DOMContentLoaded', ccFillTagline);
else ccFillTagline();
"""

# FAMILIES becomes data. Regexes arrive as strings and compile at runtime so
# the account book can come from config or be derived from AccountTeamMember.
FAMILIES_BLOCK = """const FAMILIES = (CC.families || []).map(function(f){
  return {slug:f.slug, disp:f.disp, tier:f.tier, seg:f.seg,
          re:new RegExp(f.re, f.reFlags || 'i')};
});"""

# (label, pattern, replacement, required)
RULES = [
    # --- connector tool names -------------------------------------------
    ("tool:SF",     r"^const SF\s*=\s*'mcp__[^']*';",     "", True),
    ("tool:DRIVE",  r"^const DRIVE\s*=\s*'mcp__[^']*';",  "", True),
    ("tool:SLACK",  r"^const SLACK\s*=\s*'mcp__[^']*';",  "", True),
    ("tool:SLACKP", r"^const SLACKP\s*=\s*'mcp__[^']*';", "", True),
    ("tool:GMAIL",  r"^const GMAIL\s*=\s*'mcp__[^']*';",  "", True),
    ("tool:GDRAFT", r"^const GDRAFT\s*=\s*'mcp__[^']*';", "", True),
    ("tool:GUNLAB", r"^const GUNLAB\s*=\s*'mcp__[^']*';", "", True),
    ("tool:GLABEL", r"^const GLABEL\s*=\s*'mcp__[^']*';", "", True),
    ("tool:CAL",    r"^const CAL\s*=\s*'mcp__[^']*';",    "", True),
    # --- identity --------------------------------------------------------
    ("id:ME",       r"^const ME\s*=\s*'[^']*';",          "", True),
    ("id:ME_ID",    r"^const ME_ID\s*=\s*'[^']*';",       "", True),
    ("id:SLACK_ME", r"^const SLACK_ME\s*=\s*'[^']*';",    "", True),
    ("id:APIV",     r"^const APIV\s*=\s*'[^']*';",        "", True),
    # The app derived the write tool from the read tool name at runtime. The
    # config block declares SFW itself, so this line must go or the file has a
    # duplicate `const` and NOTHING parses — a blank page, not a broken panel.
    # scripts/check_syntax.sh is what catches this class of mistake.
    ("tool:SFW-derived",
     r"^\s*const SFW\s*=\s*SF\.replace\([^;]*;[ \t]*$", "", True),
]


def sub_once(src, label, pattern, repl, required, flags=re.M, log=None):
    new, n = re.subn(pattern, lambda _m: repl, src, count=1, flags=flags)
    if n == 0:
        if required:
            sys.exit(
                f"FATAL: anchor not found: {label}  (/{pattern}/)\n"
                "The source artifact has drifted. Update the rule in "
                "parameterize.py rather than hand-editing the template."
            )
        if log is not None:
            log.append(f"  skip     {label} (absent in this source)")
    elif log is not None:
        log.append(f"  replaced {label}")
    return new


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("source")
    ap.add_argument("-o", "--out", required=True)
    args = ap.parse_args()

    src = open(args.source, encoding="utf-8").read()
    original_len = len(src)
    log = []

    # 1. Drop the embedded datasets. These never ship.
    src = sub_once(src, "data:POV_DATA",
                   r"^var POV_DATA\s*=.*$",
                   "var POV_DATA = /*d*/{{POV_DATA_JSON}};",
                   True, log=log)
    src = sub_once(src, "data:LINKEDIN_DATA",
                   r"^var LINKEDIN_DATA\s*=.*$",
                   "var LINKEDIN_DATA = /*d*/{{LINKEDIN_DATA_JSON}};",
                   True, log=log)

    # 2. Collapse the identity + tool constants into the config block.
    #    The first rule carries the whole block; the rest delete their line.
    first = True
    for label, pattern, _repl, required in RULES:
        src = sub_once(src, label, pattern,
                       CONFIG_BLOCK.strip() if first else "",
                       required, log=log)
        first = False

    # 3. The ME_ID comment names the operator and narrates a private incident.
    src = sub_once(src, "comment:ME_ID",
                   r"/\* Bernardo's real Org62 User Id\..*?returned 0 rows\. \*/",
                   "/* Resolved at setup time from the installing user's own\n"
                   "   Salesforce identity. Every query in this file keys off it. */",
                   False, flags=re.S, log=log)

    # 4. The header security comment refers to a specific person's machine.
    src = sub_once(src, "comment:header-posture",
                   r"   This is safe as a local artifact on his own machine\..*?committed to a repo\.",
                   "   This is safe as a local artifact on the operator's own machine.\n"
                   "   It would be a leak the moment it is hosted, emailed, or committed\n"
                   "   to a repo.",
                   False, flags=re.S, log=log)

    # 5. FAMILIES: hardcoded customer book -> config-driven data.
    src = sub_once(src, "data:FAMILIES",
                   r"^const FAMILIES = \[.*?^\];",
                   FAMILIES_BLOCK,
                   True, flags=re.S | re.M, log=log)

    # 5b. Two guards that config-driven values would silently defeat.
    #
    # Both of these were correct in the original because the values were
    # hardcoded and therefore always truthy. Making them configurable
    # introduced the empty/null case, and in both places the empty case
    # fails OPEN. Neither throws, so neither shows up in a syntax check.
    src = sub_once(src, "guard:WAVE_OK_DATASETS",
                   r"^const WAVE_OK_DATASETS = \[WAVE_KPI, WAVE_ACV\];",
                   "/* .filter(Boolean) is load-bearing. With an unset dataset id this\n"
                   "   list becomes [''], and the check below is q.indexOf('load \"' + '')\n"
                   "   which matches EVERY query — the allowlist protecting the one POST\n"
                   "   path would permit any dataset at all. No dataset configured must\n"
                   "   mean no analytics query allowed, i.e. fail closed. */\n"
                   "const WAVE_OK_DATASETS = [WAVE_KPI, WAVE_ACV].filter(Boolean);",
                   True, log=log)

    src = sub_once(src, "guard:ALLOWED_TOOLS",
                   r"^const ALLOWED_TOOLS = new Set\(\[SF,SFW,DRIVE,SLACK,"
                   r"SLACKP,GMAIL,GDRAFT,GUNLAB,GLABEL,CAL\]\);",
                   "/* .filter(Boolean) is load-bearing. An unconfigured connector is\n"
                   "   null, and a Set containing null makes every null tool compare\n"
                   "   equal to SFW — so an optional panel's read was routed through the\n"
                   "   write guard and refused, instead of degrading. Falsy entries must\n"
                   "   never enter the allowlist. */\n"
                   "const ALLOWED_TOOLS = new Set([SF,SFW,DRIVE,SLACK,SLACKP,GMAIL,"
                   "GDRAFT,GUNLAB,GLABEL,CAL].filter(Boolean));",
                   True, log=log)

    # Give the 12 call sites one clear error instead of a confusing refusal.
    src = sub_once(src, "guard:call-site-null",
                   r"if\(!ALLOWED_TOOLS\.has\(tool\)\) throw new Error\("
                   r"'tool not permitted by this app: '\+tool\);",
                   "if(!tool) throw new Error('that connector is not configured "
                   "in this build');\n"
                   "  if(!ALLOWED_TOOLS.has(tool)) throw new Error("
                   "'tool not permitted by this app: '+tool);",
                   True, log=log)

    # 6. HPF snapshot: a pasted CRM Analytics row. Newer artifacts only.
    src = sub_once(src, "data:HPF_SNAPSHOT",
                   r"^const HPF_SNAPSHOT\s*=\s*\{.*?^\};",
                   "const HPF_SNAPSHOT = CC.hpfSnapshot || null;",
                   False, flags=re.S | re.M, log=log)

    # 7. Manager name in the audience picker.
    src = sub_once(src, "ui:manager-option",
                   r'<option value="mike">For Mike — my manager</option>',
                   '<option value="mgr">For {{MANAGER_FIRST}} — my manager</option>',
                   False, log=log)

    # 8. Team Slack channels.
    src = sub_once(src, "data:slack-channels",
                   r"'#data-360-pricing-ama'",
                   "(CC.slackChannels && CC.slackChannels[0]) || ''",
                   False, log=log)

    out = open(args.out, "w", encoding="utf-8", newline="\n")
    out.write(src)
    out.close()

    print("\n".join(log))
    print(f"\n{args.source}  {original_len:,} bytes")
    print(f"{args.out}  {len(src):,} bytes "
          f"({100 * len(src) / original_len:.0f}% of source)")
    print("\nNow run scan_pii.py on the template before committing it.")


if __name__ == "__main__":
    main()
