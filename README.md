# RevOps MEDDICC Agent

Your sales calls contain the truth about every deal's health, but that
truth usually dies in a rep's head or a forgotten Gong recording. This
agent listens to every call, reads it against your qualification
methodology, and keeps every deal in HubSpot honestly scored, every
night, without anyone doing manual review.

Each night it re-evaluates your full active pipeline. It pulls the
latest call transcripts, scores every deal on MEDDICC (or MEDDPICC,
SPICED, or BANT, configurable to how your team actually sells), and
writes the scores straight back to HubSpot so reps and managers see
the same picture. It flags risk before it becomes a surprise in the
forecast call, and it gets sharper over time as it learns your team's
patterns.

Beyond nightly scoring, it runs a weekly analytics pass across the
whole pipeline:

- **Waterfall tracking**: see exactly where deals are moving forward,
  sliding back, or dying, stage by stage
- **Win/loss narratives**: automatically extracted from call evidence,
  not just the close reason field
- **Objection log**: a searchable record of what prospects actually
  pushed back on
- **Feature-gap backlog**: requested features pulled straight from
  calls, ranked by how often and how severely they come up

---

Interested in forward deployment for your team? Reach out:

- Email: jeff@revopsimpact.com
- LinkedIn: [linkedin.com/in/jeffbethechange](https://linkedin.com/in/jeffbethechange)

---

## Setup: three steps

### Step 1 · Credentials

Open this repo in Claude Code. If this is a fresh fork,
Claude Code will detect the missing config files and guide
you through setup automatically.

Just open the project and say: **"set up this repo"**

Claude Code will:
- Walk through every credential and API key
- Write config/client.yaml and config/context.yaml
- Discover your HubSpot stage IDs
- Set up Supabase
- Verify everything before the first run

### Step 2 · Add GitHub Secrets

After Claude Code generates your .env file, add the
values as GitHub Secrets:

**repo → Settings → Environments → Agent → Add Secret**

Or with the GitHub CLI:
```bash
gh secret set --env Agent --env-file .env
```

### Step 3 · First run

Go to: **Actions → MEDDICC Agent Nightly Run → Run workflow**

Watch the logs. First run analyzes your full active pipeline.
After that the agent runs every night at 2am UTC automatically.

### What runs automatically

| Time (UTC) | Job | What it does |
|---|---|---|
| 1:00 AM | Daily Deal ETL | Updates active deal index from HubSpot |
| 1:30 AM | Daily Calls ETL | Fetches new calls for active deals |
| 2:00 AM | MEDDICC Agent | Analyzes deals, writes to HubSpot + Supabase |

---

## Call intelligence platforms

The agent supports two call recording platforms:

**Fireflies** (default): Fireflies.ai call transcripts
- Most common for SMB/mid-market
- Simple API key authentication
- Set `call_tools.primary: "fireflies"` in config/client.yaml

**Gong**: Gong.io enterprise call intelligence
- Enterprise standard for larger sales teams
- Provides richer structured data (topics, action items, talk time)
- Requires Access Key + Access Key Secret
- Set `call_tools.primary: "gong"` in config/client.yaml

Claude Code will automatically detect your choice during setup
and collect the right credentials.

---

## What runs nightly

```
2am UTC: GitHub Actions fires
  → Load active deals from deal index
  → For each deal: load call cache → context builder (Haiku)
  → Generator (Sonnet) → Evaluator (Haiku) → Reflection gate
  → Write analysis to GitHub output/
  → Write 6 MEDDICC scores to HubSpot deal properties
  → Write analysis to Supabase for query layer
  → Update CLAUDE.md via PR if new patterns emerge
```

## What runs weekly (analytics workflow)

```
Sundays 3am UTC: GitHub Actions fires
  1. Analytics deal ETL: fetch all deals (all stages, both analyzed and analyze:false pipelines)
  2. Snapshot deals: capture point-in-time pipeline state to deals_snapshot table
  3. Compute waterfall: track qualified pipeline movement across 5 categories (new, newly qualified, forward, backward, won, lost) with reconciliation check
  4. Generate win/loss narratives: extract call evidence and compare to stated close reasons
  5. Extract objections: categorize and store per-company objections from call transcripts
  6. Extract feature gaps: identify and severity-score requested features from calls
```

**Output:** Waterfall movements in `waterfall_weekly` table, win/loss patterns, objection vault, and feature request backlog. All queryable via Supabase or the CRO agent.

---

## Files to know

| File | What it does |
|---|---|
| `scripts/run_nightly.py` | Main orchestration, runs every night |
| `scripts/meddicc_agent.py` | Generator + evaluator + reflection loop |
| `scripts/etl_calls.py` | Builds call cache from CSV exports |
| `scripts/etl_deals.py` | Builds deal index from HubSpot |
| `prompts/CLAUDE.md` | Generator instructions, edit to calibrate |
| `prompts/evaluator_rubric.md` | Evaluation criteria, auto-improves |
| `config/client.yaml` | Your HubSpot stage IDs and thresholds |
| `config/context.yaml` | Your competitors, objections, feature gaps |
| `memory/calls/` | Call cache, 1 JSON per company |
| `memory/learnings/` | What the agent is learning |
| `output/` | MEDDICC analysis files |

---

## Costs

| Scenario | Cost |
|---|---|
| First full pipeline run | ~$3-5 |
| Nightly steady state | ~$0.10-0.30 |
| Monthly total | ~$10-15 |

---

## Skills for Claude.ai and Claude Code

This repo includes two onboarding skills:

- `skills/revops-agent-setup/SKILL.md`: credential setup wizard
- `skills/revops-client-context/SKILL.md`: client context onboarding

**In Claude Code (desktop app):**
The skills run automatically when you open a fresh fork (missing config files).
Claude Code will proactively offer to guide you through setup.

**In Claude.ai (web/mobile):**
Copy the contents of each `SKILL.md` file into Claude.ai's custom skill creator.
Once saved, trigger by saying "start client onboarding" or "set up credentials".
