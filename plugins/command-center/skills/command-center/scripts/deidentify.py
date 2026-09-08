#!/usr/bin/env python3
"""
deidentify.py — MAINTAINER TOOL. Phase 2, runs after parameterize.py.

    python3 deidentify.py template/index.html.tmpl

parameterize.py handles structure: the constants another install must override
or the app returns zero rows. This handles everything else the original author
wrote as themselves —

  * the persona baked into the LLM prompt blocks (name, role, segment, products)
  * colleague and manager names in code paths and prompt strings
  * real deal figures quoted inside explanatory comments
  * third-person prose ("his forecast") that reads wrong for anyone else

Why this is a separate pass: phase 1 is mechanical and safe to re-run against
any artifact version. This pass edits prose, so it needs human review of the
diff every time. Run it, read the diff, then run scan_pii.py as the gate.

Edits in place. Keep the template under version control so the diff is legible.
"""

import re
import sys

# ---------------------------------------------------------------------------
# Code sites: values another install must actually override.
# (label, pattern, replacement, count, flags)
# ---------------------------------------------------------------------------
CODE = [
    # Header tagline -> config-driven.
    ("ui:tagline",
     r'<div class="tagline">Bernardo Medrado[^<]*</div>',
     '<div class="tagline" id="ccTagline"></div>', 1, re.S),

    # Persona header of the methodology prompt.
    ("prompt:persona",
     r"YOU ARE writing as Bernardo Medrado, ([^\n,]+) at Salesforce,\s*\n"
     r"selling ([^\n]*?) into ([^\n]*?)\.",
     "YOU ARE writing as ${CC_PERSONA_NAME}, ${CC_PERSONA_ROLE} at Salesforce,\n"
     "selling ${CC_PERSONA_PRODUCTS} into ${CC_PERSONA_SEGMENT}.", 1, re.S),

    ("prompt:signoff",
     r'Sign off "Bernardo"\.',
     'Sign off "${CC_PERSONA_FIRST}".', 1, 0),

    # Own-message filter in the Slack parser.
    ("code:self-name",
     r"who\.trim\(\) === 'Bernardo Medrado'",
     "who.trim() === CC.user.fullName", 1, 0),

    # Analytics dataset row matching.
    ("code:HPF_ME",
     r"const HPF_ME = 'Medrado';",
     "const HPF_ME = CC.user.analyticsName || "
     "(CC.user.fullName || '').split(' ').pop();", 1, 0),
    ("code:HPF_SEG",
     r"const HPF_SEG = 'ENTR';",
     "const HPF_SEG = CC.user.segment || 'ENTR';", 1, 0),

    # Org-wide CRM Analytics datasets: same for every colleague, but pinning
    # them in config means a dataset id change is a config edit, not a patch.
    ("code:WAVE_KPI",
     r"const WAVE_KPI  = '[^']*';",
     "const WAVE_KPI  = CC.sf.waveKpiDataset;", 1, 0),
    ("code:WAVE_ACV",
     r"const WAVE_ACV  = '[^']*';",
     "const WAVE_ACV  = CC.sf.waveAcvDataset;", 1, 0),

    # Hardcoded Slack id inside a search query.
    ("code:slack-self-query",
     r"from:<@U089AGUQEMQ>",
     "from:<@'+SLACK_ME+'>", 1, 0),

    # Forecast audience block: manager and core AE names.
    ("prompt:audience",
     r"\(aud==='mike' \? ' to Mike McMaster, his manager, on a forecast call\.'\s*\n"
     r"\s*: aud==='core' \? ' to [^']*, the core AEs whose accounts these are\.'\s*\n"
     r"\s*: ' to himself, as prep notes before the call\.'\)",
     "(aud==='mgr' ? ' to '+MANAGER_NAME+', your manager, on a forecast call.'\n"
     "     : aud==='core' ? ' to '+coreAeList()+', the core AEs whose accounts "
     "these are.'\n"
     "     : ' to yourself, as prep notes before the call.')", 1, re.S),

    # The four core AEs this role supports. MUST run before the name sweeps:
    # this is a code array, and letting a prose sweep rewrite the strings
    # silently breaks isCoreAE(), the By-core-AE grouping and CORE_AES.join().
    ("code:CORE_AES",
     r"const CORE_AES = \[[^\]]*\];",
     "const CORE_AES = (CC.coreAes || []).map(function(a){ "
     "return a.name || a; });", 1, 0),

    ("ui:core-ae-option",
     r'<option value="core">For [^<]*</option>',
     '<option value="core">For the core AEs</option>', 1, 0),

    # A core AE's name split across a JS concatenation, so no single line ever
    # contains it and a line-based denylist cannot see it. This string is fed
    # into an LLM prompt, so the name also left the machine at runtime.
    ("prompt:core-ae-ownership",
     r"'- He is the Digital specialist on accounts owned by [^']*'\+\s*\n"
     r"\s*'Henninger\. Never imply a deal is his to move unilaterally; where an '\+",
     "'- You are the Digital specialist on accounts owned by the core AEs. '+\n"
     "    'Never imply a deal is yours to move unilaterally; where an '+",
     1, re.S),

    # Named colleague, three internal Slack channels and dated citations, all
    # in user-facing HTML.
    ("ui:hpf-sources",
     r"'<p>Manal Houri, <strong>#broadcast-the-daily</strong>.*?</details>';",
     "'<p>The 35+ weekly baseline reflects consistent engagement and is '+\n"
     "    'explicitly an on-ramp, not a pass/fail threshold, and the FY27 "
     "org-wide '+\n"
     "    'target is &gt;90%. Both come from internal enablement channels, and "
     "the '+\n"
     "    'metric is contested internally.</p></div></details>';",
     1, re.S),

    # A customer account named as the reference deal for a play.
    ("content:beachhead-account",
     r"The proven pattern is the Zahn Labs Beachhead play — land narrow",
     "The proven pattern is a narrow beachhead play — land narrow", 1, 0),

    # Team channels hardcoded in UI copy. Renders from config instead, which
    # also gives CC.slackChannels its only consumer.
    ("ui:source-channels",
     r"'channels: <strong>#data-360-pricing-ama</strong> for pricing, '\+\s*\n"
     r"\s*'<strong>#help-sell-agentforce-flexible-agreement</strong> for "
     r"contract shape, and the '\+",
     "'channels: '+ ((CC.slackChannels||[]).map(esc).join(', ') "
     "|| 'your team\\'s pricing and contract-shape channels') +', and the '+",
     1, re.S),

    # Internal dashboard URL. CC.links.dashboard already existed, unused.
    ("ui:dashboard-link",
     r"https://prod-uswest-c\.online\.tableau\.com/t/[^']*",
     "'+ (CC.links && CC.links.dashboard || '#') +'", 1, 0),

    # Internal CRM Analytics dataset name, in a comment and in UI copy.
    ("data:dataset-name",
     r"sdm_hpc_specialist_kpi_live_dataset",
     "the specialist KPI dataset", 0, 0),

    # Reference links.
    ("ui:playbook-link",
     r"https://docs\.google\.com/presentation/d/[A-Za-z0-9_-]+/edit",
     "'+ (CC.links && CC.links.playbook || '#') +'", 1, 0),
]

# ---------------------------------------------------------------------------
# Comments quoting real pipeline. Replaced with arithmetically equivalent
# round numbers so the engineering point survives but the deal does not.
# ---------------------------------------------------------------------------
COMMENTS = [
    ("comment:attribution-example",
     r"Worked example from his live book: \"Henry Schein- A1E Upgrade\" carries\s*\n"
     r"[^*]*?up as a huge \"Not yet attributed\" slice\.",
     "Worked example. A deal carries Amount = $1,000,000, of which Data 360 is\n"
     "   $90,000 and Agentforce $90,000. Specialist credit is $180,000; the other\n"
     "   $820,000 is Sales, Service, Platform and industry cloud — the core AE's\n"
     "   number, not yours. Summing Amount inflates that one deal 5.5x, and the\n"
     "   difference shows up as a large \"Not yet attributed\" slice.", re.S),

    ("comment:core-ae-credit",
     r"This was the other way round, and on live data that put every Rotech and\s*\n"
     r"\s*Cook deal under the account's mapped core AE — so the two core AEs who\s*\n"
     r"\s*actually own that pipeline showed \$0, and \$1\.35M was credited to someone\s*\n"
     r"\s*who owns none of it\.",
     "This was the other way round, and on live data that filed deals under the\n"
     "     account's mapped core AE — so the AEs who actually own that pipeline\n"
     "     showed $0, and seven figures were credited to someone who owns none\n"
     "     of it.", re.S),

    ("comment:hpf-proxy",
     r"On his live data the ACV proxy read \$135,982 where the\s*\n"
     r"\s*dashboard says \$0, and the PipeGen proxy read \$1\.53M against a real\s*\n"
     r"\s*\$106,517 — different definitions, not rounding\.",
     "On live data the locally-computed ACV proxy disagreed with the dashboard\n"
     "     outright, and the PipeGen proxy was off by more than 10x — different\n"
     "     definitions, not rounding.", re.S),

    ("comment:segment-confirmed",
     r"ENTR/PubSec, confirmed by Bernardo — it sets every threshold below",
     "ENTR/PubSec — it sets every threshold below", 0),

    # Matches BOTH lines of the original sentence. Matching only the second
    # line left an orphaned "or Guy" dangling on the first and produced a
    # sentence that read as nonsense.
    ("comment:core-ae-roles",
     r"Most of the opportunities in this book belong to [^\n]*\s*\n"
     r"\s*Henninger — Bernardo is the Digital specialist on their accounts, "
     r"not the",
     "Most of the opportunities in this book belong to the core AEs — you are\n"
     "   the Digital specialist on their accounts, not the", re.S),

    # Invented example naming a real core AE.
    ("comment:owed-example",
     r'"What do I owe Adam this\s*\n?\s*week" was unanswerable\.',
     '"What do I owe this core AE this week" was unanswerable.', re.S),

    # Matches the PRE-sweep text: this list runs before SWEEPS, so the
    # vertical is still spelled out here. Matching the post-sweep wording
    # ("...substance. your segment only.") can never fire.
    ("comment:segment-substance",
     r"Segment-specific substance\. Healthcare (?:&amp;|&) Life Sciences only\.",
     "Segment-specific substance for the configured vertical.", 0),

    ("comment:data-posture",
     r"of Bernardo's own account strategy is embedded in this file, including named",
     "of the operator's own account strategy may be embedded in this file, "
     "including named", 0),
]

# ---------------------------------------------------------------------------
# Blanket sweeps. Applied last, to whatever survived the targeted rules.
# ---------------------------------------------------------------------------
SWEEPS = [
    # Possessives FIRST, and as their own rule. A single r"Name(?:'s)?" pattern
    # swallows the apostrophe-s and produces "the operator own account
    # strategy" — grammatically broken prose scattered through the comments.
    ("sweep:fullname-poss", r"Bernardo Medrado's", "the operator's"),
    ("sweep:fullname", r"Bernardo Medrado", "the operator"),
    ("sweep:firstname-poss", r"\bBernardo's", "the operator's"),
    ("sweep:firstname", r"\bBernardo\b", "the operator"),
    ("sweep:manager-poss", r"Mike McMaster's", "the manager's"),
    ("sweep:manager", r"Mike McMaster", "the manager"),
    # Core AE names in prose. The CORE_AES array is handled above, so these
    # only hit comments and UI copy.
    ("sweep:core-ae-1p", r"Will Clarke's", "the core AE's"),
    ("sweep:core-ae-1", r"Will Clarke", "the core AE"),
    ("sweep:core-ae-2p", r"Guy Henninger's", "the core AE's"),
    ("sweep:core-ae-2", r"Guy Henninger", "the core AE"),
    ("sweep:core-ae-3p", r"Adam Rowe's", "the core AE's"),
    ("sweep:core-ae-3", r"Adam Rowe", "the core AE"),
    ("sweep:core-ae-4p", r"Cameron Youash's", "the core AE's"),
    ("sweep:core-ae-4", r"Cameron Youash", "the core AE"),
    # No bare-first-name sweep here on purpose: \bWill\b matches the English
    # auxiliary verb and would shred the comments. First names are caught by
    # scan_pii.py's denylist instead, which reports rather than rewrites.
    # Role, methodology and the Marketing Cloud / Data 360 / Agentforce
    # attribution logic are deliberately NOT swept — this template targets the
    # Marketing Cloud specialist role and that is the substance of it. Only the
    # vertical varies across peers, so it comes from config.
    ("sweep:segment", r"Healthcare (?:&amp;|&) Life Sciences",
     "your segment"),
    # Prompt-block headings written in the third person.
    ("sweep:prompt-his", r"=== HIS ([A-Z ]+) ===", r"=== YOUR \1 ==="),
    ("sweep:prompt-he-say",
     r"the forecast narrative he will actually say out loud",
     "the forecast narrative you will actually say out loud"),
]


def main():
    if len(sys.argv) != 2:
        sys.exit("usage: deidentify.py TEMPLATE")
    path = sys.argv[1]
    src = open(path, encoding="utf-8").read()
    log, missing = [], []

    for label, pat, repl, count, flags in CODE:
        src, n = re.subn(pat, lambda _m, r=repl: r, src, count=count,
                         flags=flags)
        (log if n else missing).append(f"  {'ok  ' if n else 'MISS'} {label}"
                                      + (f" x{n}" if n else ""))

    for label, pat, repl, flags in COMMENTS:
        src, n = re.subn(pat, lambda _m, r=repl: r, src, count=1, flags=flags)
        (log if n else missing).append(f"  {'ok  ' if n else 'MISS'} {label}")

    for item in SWEEPS:
        label, pat, repl = item
        src, n = re.subn(pat, repl, src)
        log.append(f"  ok   {label} x{n}")

    # The persona tokens all sit inside METHOD, which is a backtick template
    # literal — so they expand to ${...} interpolation, NOT to '+ x +' string
    # concatenation. Getting this wrong does not throw: the concatenation
    # syntax renders literally into the prompt, and every generated draft
    # quietly addresses itself to "'+ (CC.user.fullName||'') +'".
    PERSONA = {
        "${CC_PERSONA_NAME}":     "${CC.user.fullName||''}",
        "${CC_PERSONA_ROLE}":     "${CC.user.roleTitle||'Account Executive'}",
        "${CC_PERSONA_PRODUCTS}": "${(CC.products||[]).join(', ')}",
        "${CC_PERSONA_SEGMENT}":  "${CC.user.segmentName||'your segment'}",
        "${CC_PERSONA_FIRST}":    "${CC.user.firstName||''}",
    }
    for token, repl in PERSONA.items():
        src = src.replace(token, repl)

    open(path, "w", encoding="utf-8", newline="\n").write(src)

    print("\n".join(log))
    if missing:
        print("\nRules that did not match — the source has drifted, "
              "check each by hand:")
        print("\n".join(m for m in missing if "MISS" in m))
    print("\nNow: read the diff, then run scan_pii.py as the gate.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
