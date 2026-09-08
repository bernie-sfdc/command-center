---
name: command-center
description: Build or rebuild the user's personal Marketing Cloud specialist Command Center — a single-page dashboard over their own Salesforce pipeline, specialist forecasts, calendar, inbox and Slack. Use when the user says "set up my command center", "build my command center", "create my own command center", "rebuild my command center", "update my command center config", or asks to change which accounts, core AEs or quota it tracks. This skill generates a personalized artifact from a shared template; it does not read anyone else's data.
---

# Command Center setup

This skill turns a shared template into one person's Command Center. It asks for
what only they can tell you, resolves what can be resolved from their own
connectors, then builds and publishes the artifact.

The template targets **one role**: the Marketing Cloud specialist AE who carries
L1 Marketing Cloud and L2 Data 360 / Agentforce on accounts owned by other core
AEs. The specialist attribution logic — separating your share of a deal from the
core AE's Sales, Service and Platform share — is the substance of the tool. If
the user is a core AE rather than a specialist, say so plainly and stop: the
numbers would mislead them rather than help.

## Before you start

Check the plugin directory for `template/index.html.tmpl`. If it is missing,
the plugin was installed without its template — tell the user and stop.

## Step 1 — Interview

Ask with a single multi-question prompt, not one question at a time. Do not
guess any of these; every one changes what the app computes.

1. **Their role and specialisation** — role title, vertical/segment, and the
   levels they carry. Defaults: "Enterprise Digital Account Executive",
   segment code `ENTR`.
2. **Their manager's name** — used for the "write this for my manager" audience
   in the forecast narrative tab.
3. **The core AEs they support** — full names as they appear in Salesforce, in
   the order they want them displayed. This drives the By-core-AE tab and the
   attribution split. Usually two to four people.
4. **Their FY quota** — optional here; the app also accepts it in-page and
   stores it locally.
5. **Team Slack channels** worth watching, and links to the FY playbook deck
   and performance dashboard if they have them.

Do **not** ask them to list their accounts. Leave `families` empty: the app
derives the book from `AccountTeamMember` on first load, which is both less
work and more accurate than a hand-typed list. Offer to add family matching
rules later, once they have seen what the derived book looks like.

## Step 2 — Resolve their Salesforce identity from the org

Their Salesforce User Id is the single most important value in the config, and
the one most likely to be wrong. **Never guess it, never accept a
copy-pasted-from-somewhere id without checking, and never reuse one from
another install.** A syntactically valid but wrong id makes every panel return
zero rows, which looks exactly like a broken connector — this has already cost
one debugging session.

Query it from their own org with their Salesforce connector:

```sql
SELECT Id, Name, Username FROM User WHERE Username = '<their work email>'
```

Confirm the returned `Name` matches the person you are talking to before using
the `Id`. Use that `Name` verbatim as `user.fullName`: the app filters the
user's own Slack messages by exact string match, so a nickname means they see
their own posts in their signals feed.

## Step 3 — Resolve their connector tool names

The `mcp__<id>__<tool>` names in your own tool list are **per-install**. The
template deliberately contains none of them; they come from the machine that
will run the app.

Read your own available tools and map them into `config.tools`:

| Config key | Look for |
|---|---|
| `sfRead` | Salesforce `dispatch_readonly` |
| `sfWrite` | Salesforce `dispatch` |
| `driveSearch` | Drive `search_files` |
| `slackSearchPublic` | Slack `slack_search_public` |
| `slackSearchAll` | Slack `slack_search_public_and_private` |
| `gmailSearch` | Gmail `search_threads` |
| `gmailCreateDraft` | Gmail `create_draft` |
| `gmailLabelThread` / `gmailUnlabelThread` | Gmail `label_thread` / `unlabel_thread` |
| `calendarList` | Calendar `list_events` |

Set any connector they do not have to `null`. The app degrades those panels
instead of failing. Only `sfRead` is required — without Salesforce there is no
app, so if it is missing, stop and tell them which connector to add.

Tell the user which panels will be inactive given what they have connected,
before you build. A quiet empty panel reads as a bug.

## Step 4 — Write the config and build

Write `command-center.config.json` in the user's working folder, validated
against `reference/config.schema.json`. Then:

```bash
python3 scripts/build.py \
  --template template/index.html.tmpl \
  --config   command-center.config.json \
  --out      index.html

./scripts/check_syntax.sh index.html
```

`build.py` refuses to write on a bad config and prints a `note:` for every
degraded panel. Relay those notes. `check_syntax.sh` is not optional: the app
is one large inline script, so a parse error renders a blank page rather than a
broken panel, and a blank page is indistinguishable from a connector outage.

## Step 5 — Publish as an artifact

Create the artifact from the built `index.html`. When declaring its
`mcp_tools`, pass **every non-null value from `config.tools`** — including
`sfWrite`. The original app derived the write tool name at runtime but never
declared it, so every forecast save was silently refused at the bridge. If they
want to save SFRs and next steps from the page, `sfWrite` must be declared.

Then confirm with the user: open it, check the header shows their own name and
segment, and check the pipeline panel returns rows. If the panels are empty but
the connector pills show green, the User Id from Step 2 is wrong — go back and
re-query it rather than adjusting anything else.

## Rebuilding

Config changes are cheap. Edit `command-center.config.json`, re-run Step 4, and
update the existing artifact rather than creating a second one. The user's own
in-page state — quota, dismissed items, week-over-week snapshot — lives in
`localStorage` under `ae-cc:` keys and survives a rebuild.

## Data handling

The template ships with no customer data. The moment it is built and loaded it
reads the operator's own pipeline, and if they add POV notes it will hold named
customer stakeholders and deal values. So:

- The built `index.html` and `command-center.config.json` are **local only**.
  Never commit either, never email them, never upload them to a host.
- Only `template/index.html.tmpl` is shareable, and only after
  `scripts/scan_pii.py` passes on it.
- Everything the app reads goes through the user's own connectors under their
  own permissions. It cannot see another person's pipeline, and it should not
  be used to try.

If the user asks to share their *built* command center with a colleague, the
answer is to have the colleague install the plugin and run this skill — not to
send them the file.
