#!/usr/bin/env python3
"""
scan_pii.py — gate before the template is committed or shared.

    python3 scan_pii.py template/index.html.tmpl

Exit 0 = clean. Exit 1 = findings. Wire this into CI and a pre-commit hook;
a template that leaks one account name is worse than no template, because it
will be copied to everyone who installs the plugin.

Structural patterns only, plus a small denylist for the known-bad values from
the original artifact. It will produce false positives on prose. Read every
finding; do not add blanket ignores.
"""

import re
import sys

# Values known to exist in the source artifact. A hit here is a hard failure.
DENYLIST = [
    "bmedrado", "Bernardo", "Medrado", "Mike McMaster", "888333",
    "005ed000000EZ4LAAW", "U089AGUQEMQ",
    "Henry Schein", "henryschein", "Parexel", "ClinPhone", "Cook Medical",
    "Organon", "Dermavant", "PerkinElmer", "Perkin Elmer", "Covaris",
    "BioFire", "bioMerieux", "biomerieux", "Rotech", "DenMat", "Den-Mat",
    "BioHorizons", "Butler Animal", "Ortho2", "MicroMD", "Regentec",
    "eAssist", "DentalPlans", "Ace Surgical",
    # Core AEs this role supports. Bare first names are listed because the
    # deidentify sweeps deliberately do not rewrite them (\bWill\b collides
    # with the auxiliary verb), so the gate has to catch them by hand.
    # Surnames listed SEPARATELY from full names. A full-name-only denylist
    # missed "the core AE and Guy '+ 'Henninger" — the name was split across a
    # JS concatenation so no single line contained it. join_concats() now
    # normalizes that, but surname entries are the belt to its braces.
    "Will Clarke", "Guy Henninger", "Adam Rowe", "Cameron Youash",
    "Henninger", "Youash", "Clarke",
    "Manal Houri", "Houri", "Zahn Labs", "Zahn",
    "sdm_hpc_specialist", "broadcast-the-daily", "th-fy27-v2mom-feedback",
    "Manish Rai", "Heintzelman", "Dillon", "Wexler", "Ty Ford",
    "Trinh Clark", "Brennan", "Rexer", "Sarah Anders", "Kremski",
    "Vallotti", "Luann Bridges",
    "0Fb3y0000001WXkCAM", "0Fced00000BORYbCAP",
    "Ramping, not participating",
]

# Structural patterns. (label, regex, note)
PATTERNS = [
    ("salesforce email", r"[A-Za-z0-9._%+-]+@salesforce\.com",
     "operator or colleague identity"),
    ("SF 15/18-char id", r"\b00[0-9A-Za-z]{1}[0-9A-Za-z]{12}(?:[0-9A-Za-z]{3})?\b",
     "record or user id"),
    ("Slack user id", r"\bU0[A-Z0-9]{7,10}\b", "Slack member id"),
    ("LinkedIn profile", r"linkedin\.com/in/[A-Za-z0-9\-_%]+",
     "named individual"),
    ("Google doc id", r"docs\.google\.com/\w+/d/[A-Za-z0-9_-]{20,}",
     "internal document"),
    # Handled by suspicious_money() instead of a flat regex: the app is full of
    # legitimate round thresholds ($25K, $100K) and formatter test values, and a
    # rule that flags all of them gets ignored, which defeats the gate.
    ("dollar figure", None, "possible ACV/TCV — check it is not real"),
    ("unresolved connector id",
     r"mcp__[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}__\w+",
     "hardcoded per-install connector — must come from CC.tools"),
    ("employee id-ish", r"\bEMP_ID\s*:\s*'[^']+'", "employee number"),
    # See suspicious_channel(): a flat #token pattern flags hex colours and
    # every CSS id in the stylesheet, which buries the real findings.
    ("slack channel", None,
     "internal channel name — should come from CC.slackChannels"),
    ("internal host", r"\b[\w.-]*\.(?:tableau\.com|my\.salesforce\.com)\b",
     "internal URL — should come from CC.links"),
    ("analytics dataset", r"\bsdm_[a-z0-9_]+\b",
     "internal dataset name — should come from CC.sf"),
]

# Lines matching these are app logic, not data, and are expected to mention
# the shapes above. Keep this list SHORT and specific.
#
# Comments are deliberately NOT exempt. An earlier version skipped every line
# starting with /*, * or // — 7% of the file — and the comments are precisely
# where the real deal figures and colleague names were quoted. An exemption
# that broad is indistinguishable from not scanning.
ALLOW_LINE = [
    r"scan_pii", r"DENYLIST", r"PATTERNS",
    r"CC\.tools\.|CC\.user\.|CC\.sf\.|CC\.links\.|CC\.slackChannels",
    r"\{\{CC_CONFIG_JSON\}\}",
    r"REPLACE-WITH-YOUR",
]

CONT = re.compile(r"['\"]\s*\+\s*$")


def join_concats(lines):
    """Yield (first_lineno, logical_text) with JS concatenations merged.

    The app builds long strings as  '...'+\\n  '...'+\\n  '...'  so a name can
    straddle two physical lines and never appear whole on either. A line-based
    denylist cannot see that; this is what let a core AE's surname through.
    """
    out, buf, start = [], None, None
    for i, line in enumerate(lines, 1):
        if buf is None:
            buf, start = line, i
        else:
            buf += " " + line.lstrip()
        if CONT.search(line.rstrip()):
            continue                      # string continues on the next line
        out.append((start, buf))
        buf, start = None, None
    if buf is not None:
        out.append((start, buf))
    return out


MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s?([KMB])?\b")

# Lines whose money values are formatter fixtures or documented thresholds.
MONEY_OK_CONTEXT = re.compile(
    r"money|fmt|format|round|boundary|threshold|suffix|digit|render|"
    r"worked example|\bK-suffixed\b|nearest", re.I)


def suspicious_money(line):
    """Real ACV looks arbitrary. Round numbers and fixtures do not.

    Flags a figure only when it has 4+ significant digits and is not a round
    thousand — $135,982 or $819,059, but not $100K, $1M or $90,000.
    """
    if MONEY_OK_CONTEXT.search(line):
        return []
    hits = []
    for m in MONEY.finditer(line):
        raw, suffix = m.group(1).replace(",", ""), m.group(2)
        try:
            val = float(raw)
        except ValueError:
            continue
        if suffix:                      # $1.2M, $100K — abbreviated, coarse
            continue
        if val == 0 or val % 1000 == 0:  # round thousand
            continue
        digits = raw.replace(".", "").lstrip("0").rstrip("0")
        if len(digits) >= 4:
            hits.append(m.group(0))
    return hits


CHANNEL = re.compile(r"#([a-z0-9][a-z0-9-]{3,})\b")
HEXISH = re.compile(r"^[0-9a-f]{3,8}$")
# Generic placeholders in prose and CSS ids, not real channels.
CHANNEL_NOISE = {"channel-or", "channel-or-dm", "subnav"}


def suspicious_channel(line):
    """A real channel name is hyphenated; CSS ids and hex colours are not."""
    hits = []
    for m in CHANNEL.finditer(line):
        # Strip trailing hyphens: the greedy class swallows them, so a prose
        # placeholder like "#channel-or-DM" arrives as "channel-or-" and slips
        # past an exact-match noise set.
        tok = m.group(1).rstrip("-")
        if HEXISH.match(tok) or "-" not in tok or tok in CHANNEL_NOISE:
            continue
        hits.append(m.group(0))
    return hits


def main():
    if len(sys.argv) < 2:
        sys.exit("usage: scan_pii.py FILE [FILE...]")

    total = 0
    for path in sys.argv[1:]:
        lines = open(path, encoding="utf-8").read().splitlines()
        findings = []

        # Scan the concatenation-merged view. Line numbers are the first
        # physical line of each logical string, so a finding may sit a line or
        # two below the number reported.
        for i, line in join_concats(lines):
            if any(re.search(p, line, re.I) for p in ALLOW_LINE):
                continue
            snippet = line.strip()[:120]

            for bad in DENYLIST:
                if bad.lower() in line.lower():
                    findings.append((i, "DENYLIST", bad, snippet))

            for label, rx, note in PATTERNS:
                if rx is None:
                    continue
                for m in re.finditer(rx, line):
                    findings.append((i, label, m.group(0)[:60], note))

            for hit in suspicious_money(line):
                findings.append((i, "dollar figure", hit,
                                 "arbitrary figure — verify it is not real ACV"))

            for hit in suspicious_channel(line):
                findings.append((i, "slack channel", hit,
                                 "internal channel — use CC.slackChannels"))

        if findings:
            print(f"\n{path}: {len(findings)} finding(s)")
            for ln, label, hit, note in findings[:200]:
                print(f"  L{ln:<6} [{label}] {hit}   -- {note}")
            if len(findings) > 200:
                print(f"  ... {len(findings) - 200} more")
        else:
            print(f"{path}: clean")
        total += len(findings)

    if total:
        print(f"\nFAIL — {total} finding(s). Do not commit or share.")
        return 1
    print("\nPASS — no personal or customer data detected.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
