# Evaluator Rubric: Pass/Fail Criteria

**Purpose:** Objective quality gate for MEDDICC analyses before CRM update.

**Rule:** ALL criteria must pass. One fail = entire analysis rejected.

---

## Criterion 1: Evidence Traceability

### PASS if:
- ✅ Every MEDDICC component with score ≥5 has direct quote
- ✅ Every "✅ Identified" status has supporting evidence
- ✅ Call numbers cited for every quote (format: "Call #N")
- ✅ Quotes match source material verbatim (not paraphrased)
- ✅ Zero instances of "seems," "appears," "probably," "likely" without evidence

### FAIL if:
- ❌ Any score ≥5 lacks quote
- ❌ Any "confirmed" claim without evidence
- ❌ Paraphrased evidence that can't be verified
- ❌ Generic statements like "the buyer mentioned metrics" without showing what they said
- ❌ More than 2 uses of hedging language ("seems," "appears") across entire analysis

### Test:
1. Pick 3 random high scores (7+)
2. Find their supporting quotes
3. Verify quotes exist in source material
4. **All 3 must pass** → Criterion passes

---

## Criterion 2: Component Coverage

### PASS if:
- ✅ All 7 MEDDICC components present (or 9 for MEDDPICC)
- ✅ Each component has status symbol (✅/⚠️/❌)
- ✅ Each component has numeric score (0-10)
- ✅ Scorecard table completely filled (no blanks, no "N/A")
- ✅ "Not discussed in this call" is acceptable (shows component was checked)

### FAIL if:
- ❌ Any component section missing
- ❌ Any component skipped "because nothing changed"
- ❌ Any score missing or marked "TBD"
- ❌ Scorecard table has empty cells or "N/A" values
- ❌ Fewer than 7 component sections (or 9 for MEDDPICC)

### Test:
1. Count component sections
2. Count scores in table
3. Check for status symbols
4. **Must equal** component count (7 or 9) → Criterion passes

---

## Criterion 3: False Gap Detection

### PASS if:
- ✅ Generator referenced Context Builder state before flagging gaps
- ✅ Gaps are things NEVER discussed, not things not discussed THIS call
- ✅ Previously confirmed items show as confirmed (not re-flagged as gaps)
- ✅ "Needs reconfirmation" differentiated from "not identified"
- ✅ Zero contradictions between "What Changed" and "Gaps Remaining"

### FAIL if:
- ❌ Flags as gap something confirmed in previous calls
- ❌ Low score (0-4) for component that Context Builder showed as confirmed
- ❌ Ignores evidence from call history
- ❌ Treats every call as starting from zero state
- ❌ "Gaps Remaining" list includes items with evidence in Context Builder

### Test:
1. Find 2 components with strong prior evidence in Context Builder
2. Check if Generator acknowledged that evidence
3. Verify those components not flagged as gaps
4. **Both must pass** → Criterion passes

---

## Criterion 4: Score Justification

### PASS if:
- ✅ Scores 0-3: No evidence OR very vague evidence only
- ✅ Scores 4-6: Some evidence but missing key details/quantification
- ✅ Scores 7-8: Strong evidence, specific, recently confirmed
- ✅ Scores 9-10: Fully qualified with multiple confirmations
- ✅ Score changes justified by new evidence in current call
- ✅ Trends (↗️/→/↘️) match actual evidence trajectory

### FAIL if:
- ❌ Score ≥7 with only one vague quote
- ❌ Score unchanged when clear new evidence added
- ❌ Score of 8+ for "seems confirmed" or single indirect mention
- ❌ ALL scores trending up (statistically impossible)
- ❌ Score increased but "What Changed" section says "Nothing new"
- ❌ Score decreased but no evidence of weakening

### Test:
1. Find highest scored component (usually 8+)
2. Count supporting quotes (need 2+ for score ≥8)
3. Check if quotes are specific (names, numbers, timelines)
4. Find lowest scored component (usually 0-4)
5. Verify it genuinely lacks evidence
6. **Both must pass** → Criterion passes

---

## Criterion 5: Internal Consistency

### PASS if:
- ✅ Deal Health aligns with component scores (can't be "Strong" with 3+ components <5)
- ✅ Stage recommendation matches MEDDICC completeness
- ✅ Risk Level matches number/severity of gaps
- ✅ Champion strength aligns with Deal Momentum
- ✅ Economic Buyer score + Decision Process score support stage position
- ✅ No contradictions between sections

### FAIL if:
- ❌ "Deal Health: Strong" but Champion is ≤4
- ❌ "Deal Health: Strong" but 3+ components <5
- ❌ Stage "Proposal" but Economic Buyer not confirmed (<6)
- ❌ "Risk Level: Low" but has "Critical Risk" flags
- ❌ Champion 9/10 but "Deal Momentum: Stalled"
- ❌ Decision Process 2/10 but stage is "Negotiating"

### Test:
1. Check: If Deal Health = "Strong", count components ≥6 (need 5+)
2. Check: If Stage = late-stage (Proposal+), Economic Buyer must be ≥6
3. Check: If Champion ≤5, Deal Health cannot be "Strong"
4. **All must pass** → Criterion passes

---

## Criterion 6: Actionability

### PASS if:
- ✅ Each action specifies WHO (person/role to engage)
- ✅ Each action specifies WHAT (specific question or goal)
- ✅ Each action ties to a specific MEDDICC gap
- ✅ Actions are achievable within stated timeframe (1-2 weeks)
- ✅ No generic advice ("follow up," "build rapport," "get clarity")
- ✅ At least one action addresses lowest-scoring component

### FAIL if:
- ❌ Any action lacks WHO (e.g., "Follow up on metrics")
- ❌ Any action lacks WHAT (e.g., "Talk to economic buyer")
- ❌ Action not tied to gap (e.g., "Send case study" when no gap requires it)
- ❌ Action too vague to execute (e.g., "Build champion")
- ❌ Zero actions address components scored <5
- ❌ Actions longer than 3 sentences (too complex)

### Examples:

✅ **PASS:**
> "Schedule 30-min call with Sarah Johnson (VP Finance) to confirm: (1) Is our $180K proposal within her signing authority? (2) What's the timeline for Q3 budget finalization?"

❌ **FAIL:**
> "Follow up on economic buyer and confirm decision process."

### Test:
1. Read top 3 recommended actions
2. Can you execute them without asking "who?" or "how?"
3. Do they reference specific gaps from the analysis?
4. **All 3 must pass** → Criterion passes

---

## Criterion 7: Stage Alignment Logic

### PASS if:
- ✅ Stage recommendation includes specific reasoning
- ✅ Reasoning cites component scores to justify stage
- ✅ If recommending stage change, exit criteria are listed
- ✅ Stage recommendation matches your defined progression
- ✅ Late-stage recommendations (Proposal+) require most components ≥6

### FAIL if:
- ❌ Recommends "Proposal" when Champion ≤4
- ❌ No explanation for stage recommendation
- ❌ Recommends advancement without stating what gaps remain
- ❌ Ignores current CRM stage mismatch without comment
- ❌ Late-stage recommendation with multiple components <5

### Stage Progression Standards (Customize These):

**Discovery** → **Scoping:**
- Identify Pain: ≥5
- Champion: ≥4
- At least 2 stakeholders engaged

**Scoping** → **Proposal:**
- Metrics: ≥6
- Economic Buyer: ≥6
- Champion: ≥6
- Decision Criteria: ≥5

**Proposal** → **Negotiating:**
- All components: ≥6
- Decision Process: ≥7
- Competition: ≥6

**Negotiating** → **Closed Won:**
- All components: ≥8
- Paper Process: ≥7 (if using MEDDPICC)

### Test:
1. Check current recommended stage
2. Verify components meet minimum scores for that stage
3. If not, check if Generator recommended stage change
4. **Must pass** → Criterion passes

---

## Rejection Thresholds

### Strict Mode (Recommended):
**Reject if ANY criterion fails**

Use during:
- Initial rollout
- Training period
- High-stakes deals ($100K+ ARR)

### Standard Mode:
**Reject if 2+ criteria fail**

Use after:
- System has 30+ approved analyses
- Rejection rate <10%
- Team comfortable with quality

### Lenient Mode (Not Recommended):
**Reject if 3+ criteria fail**

Risk:
- Poor data in CRM
- Corrupted future analyses
- Forecast inaccuracy

**Default: Strict Mode**

---

## Evaluation Checklist

Use this for each analysis:

```
[ ] 1. Evidence Traceability
    [ ] Test: Verified 3 random quotes match source
    [ ] Test: Zero unsupported high scores
    [ ] Test: No weasel words without evidence

[ ] 2. Component Coverage
    [ ] Test: Counted sections = 7 (or 9)
    [ ] Test: All scores present
    [ ] Test: All status symbols present

[ ] 3. False Gap Detection
    [ ] Test: Checked 2 prior confirmations not flagged as gaps
    [ ] Test: Low scores match actual gaps in context

[ ] 4. Score Justification
    [ ] Test: Highest score has 2+ strong quotes
    [ ] Test: Lowest score genuinely lacks evidence
    [ ] Test: Score changes match evidence changes

[ ] 5. Internal Consistency
    [ ] Test: Deal Health matches component scores
    [ ] Test: Stage matches component completeness
    [ ] Test: No contradictions between sections

[ ] 6. Actionability
    [ ] Test: Top 3 actions have WHO and WHAT
    [ ] Test: Actions tie to specific gaps
    [ ] Test: At least one addresses lowest component

[ ] 7. Stage Alignment
    [ ] Test: Stage recommendation has reasoning
    [ ] Test: Components meet stage requirements
    [ ] Test: Exit criteria clear if advancing

VERDICT: [ ] ALL PASS → APPROVED | [ ] ANY FAIL → REJECTED
```

---

## Output Format (JSON)

```json
{
  "timestamp": "2026-08-02T14:30:00Z",
  "deal_id": "12345",
  "deal_name": "Acme Corp - New Business",
  "verdict": "APPROVED",
  "quality_score": 95,
  "evaluation": {
    "criterion_1_evidence": {
      "pass": true,
      "tests_run": [
        "Verified 3 quotes match source: PASS",
        "Checked for unsupported scores: PASS",
        "Scanned for weasel words: PASS"
      ],
      "issues": []
    },
    "criterion_2_coverage": {
      "pass": true,
      "tests_run": [
        "Component count: 7/7",
        "Score count: 7/7",
        "Status symbols: 7/7"
      ],
      "issues": []
    },
    "criterion_3_false_gaps": {
      "pass": true,
      "tests_run": [
        "Checked prior confirmations: PASS",
        "Verified gaps are genuine: PASS"
      ],
      "issues": []
    },
    "criterion_4_scores": {
      "pass": true,
      "tests_run": [
        "Highest score (Champion: 8) has 3 quotes: PASS",
        "Lowest score (Competition: 3) lacks evidence: PASS",
        "Score changes justified: PASS"
      ],
      "issues": []
    },
    "criterion_5_consistency": {
      "pass": true,
      "tests_run": [
        "Deal Health aligns with scores: PASS",
        "Stage matches completeness: PASS",
        "No contradictions found: PASS"
      ],
      "issues": []
    },
    "criterion_6_actions": {
      "pass": true,
      "tests_run": [
        "Action 1 has WHO and WHAT: PASS",
        "Action 2 has WHO and WHAT: PASS",
        "Action 3 has WHO and WHAT: PASS",
        "Actions address gaps: PASS"
      ],
      "issues": []
    },
    "criterion_7_stage": {
      "pass": true,
      "tests_run": [
        "Stage reasoning present: PASS",
        "Components meet stage reqs: PASS",
        "Exit criteria clear: PASS"
      ],
      "issues": []
    }
  },
  "approved_for_crm": true,
  "notes": "High quality analysis with strong evidence throughout."
}
```

---

## Rejection Example (JSON)

```json
{
  "timestamp": "2026-08-02T14:35:00Z",
  "deal_id": "67890",
  "deal_name": "Beta Inc - Enterprise",
  "verdict": "REJECTED",
  "quality_score": 45,
  "evaluation": {
    "criterion_1_evidence": {
      "pass": false,
      "tests_run": [
        "Verified quotes: FAIL - 2/3 quotes not found in source",
        "Unsupported scores: FAIL - Economic Buyer 8/10 with no quote"
      ],
      "issues": [
        "Economic Buyer scored 8/10 but only evidence is: 'Sarah seems to have authority'",
        "Champion quote in Call #4 doesn't match transcript",
        "3 instances of 'probably' and 'seems' without supporting evidence"
      ]
    },
    "criterion_4_scores": {
      "pass": false,
      "tests_run": [
        "Champion scored 9/10 with single vague quote: FAIL"
      ],
      "issues": [
        "Champion: 9/10 but evidence is: 'Jamie has been helpful' - not sufficient for 9"
      ]
    }
  },
  "approved_for_crm": false,
  "required_fixes": [
    "Provide direct quotes for Economic Buyer (currently 8/10 with no evidence)",
    "Lower Champion score to 6/10 or provide stronger evidence of advocacy",
    "Replace 'seems' and 'probably' with direct quotes",
    "Verify all quotes exist in source material"
  ],
  "notes": "Analysis shows weak evidence quality. Return to Generator for revision."
}
```

---

## Quality Score Calculation

```
Base: 100 points
- 1: -20 if fail (Evidence Traceability)
- 2: -15 if fail (Component Coverage)
- 3: -15 if fail (False Gap Detection)
- 4: -20 if fail (Score Justification)
- 5: -10 if fail (Internal Consistency)
- 6: -10 if fail (Actionability)
- 7: -10 if fail (Stage Alignment)

Passing threshold: 70+
Excellent: 90+
Perfect: 100
```

---

## Key Principles

1. **No Benefit of Doubt:** Unclear = Fail
2. **Evidence > Inference:** "Seems" without quote = Fail
3. **Consistency is Critical:** One contradiction = Fail (Criterion 5)
4. **Protect the Memory:** Bad data poisons future analyses
5. **Strict Early, Relax Later:** Start in Strict Mode, move to Standard after stability

---

**Remember:** You're the last line of defense before CRM corruption. Better to reject a borderline analysis than approve bad data.
