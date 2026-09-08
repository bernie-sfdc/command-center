# Command Center — Marketing Cloud specialist AE

One page over your own Salesforce pipeline, specialist forecasts, calendar,
inbox and Slack. Fourteen views across Forecast, My Day, Accounts, Write and
Deal Advisor.

This repo holds a **template**, not a dashboard. You install the plugin, answer
five or six questions, and Claude builds your own copy against your own
connectors. Nobody's pipeline is visible to anyone else, and there is no shared
server, no bot token and no hosted page.

## Install

```
/plugin marketplace add <this-repo-url>
/plugin install command-center
```

Then, in Cowork:

> set up my command center

The skill interviews you, resolves your Salesforce identity from your own org,
maps your connector tool names, builds the page and publishes it as an
artifact. Expect about five minutes.

## What you need

**Required.** A Salesforce connector. Without it there is no app.

**Optional, each enabling specific views.** Gmail (inbox triage, draft
replies), Calendar (today's meetings), Slack (signals, DMs and mentions),
Drive (document lookup). Anything you have not connected leaves its panel
inactive; the skill tells you which before it builds, so an empty panel is
never a mystery.

## Who it is for

Specifically the Marketing Cloud specialist AE who carries L1 Marketing Cloud
and L2 Data 360 / Agentforce on accounts **owned by other core AEs**.

The core of the tool is the attribution split: it separates your specialist
share of a deal from the core AE's Sales, Service, Platform and industry cloud
share. Summing raw Opportunity `Amount` inflates a mixed deal by several times
and dumps the difference into a "Not yet attributed" bucket — getting that
right is most of the value here.

If you are a core AE rather than a specialist, this will mislead you. The
numbers assume you own a slice, not the whole deal.

## Your data

Read this bit.

- The **template** in this repo contains no customer data, no identities and no
  credentials. `scripts/scan_pii.py` gates every change to it, and it fails the
  original personal artifact by design.
- Your **built** `index.html` and your `command-center.config.json` are a
  different matter. They hold your identity, your book, and any POV notes you
  add — which can include named customer stakeholders and deal values. Keep
  both local. Do not commit them, email them, or upload them anywhere.
  `.gitignore` already blocks them; do not override it.
- Every read happens through your own connectors under your own permissions.
- To share the command center with a colleague, point them at this repo. Do not
  send them your file.

## Maintainer notes

The template is a **build product**, regenerated from a personal artifact.
Never hand-edit `template/index.html.tmpl`.

```bash
make template SRC=~/Desktop/ae-command-center.html
git diff -- plugins/command-center/skills/command-center/template/
make check
```

Three scripts, in order:

| Script | Does |
|---|---|
| `parameterize.py` | Structural. Pulls identity, connector names, account families and the embedded datasets into one `CC` config object. Mechanical and safe to re-run. Aborts if an anchor has drifted rather than silently skipping it. |
| `deidentify.py` | Prose and persona. Rewrites the LLM prompt blocks, colleague and manager names, and the comments that quoted real deal figures. Edits prose, so **read the diff every time**. |
| `scan_pii.py` | The gate. Denylist plus structural patterns for Salesforce ids, Slack ids, LinkedIn URLs, doc ids and arbitrary-looking dollar figures. Exit non-zero blocks the commit. |

`check_syntax.sh` parse-checks a build with `node --check`. This is not
ceremony: the app is one ~430KB inline script, so a duplicate `const` renders a
blank page with the error only in the devtools console — indistinguishable from
a connector outage. It has already caught one such break.

### When the source artifact changes

Re-run `make template` against the new version. If `parameterize.py` reports
`FATAL: anchor not found`, the app moved something the template depends on:
update the rule in the script, never the generated template.

`deidentify.py` prints `MISS` for rules that no longer match. A `MISS` usually
means the personal string it targeted has moved rather than gone — check by
hand before assuming it is clean, and trust `scan_pii.py` over your own reading.

## Status

`0.1.0`. Built and gated; not yet installed by anyone but the author. The
setup skill's Step 2 and Step 3 are the parts most likely to need adjusting on
someone else's machine, since connector naming and Org62 display names are
exactly what varies between installs.
