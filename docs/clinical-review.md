# Clinical review: LoopCloser pathways and patient messages

**Status: template, not yet filled in. No clinician has reviewed LoopCloser yet.** Nothing in this file may be
quoted, summarized or shown as a review until a real reviewer has filled it in and given permission. Until then,
every pathway and template stays labeled "pending clinical sign-off".

How to use: one copy of the review section per reviewer. Fill it in with the reviewer (or let them write it), then
commit it. If a pathway or template changes because of the review, publish a **new version** (published versions
are hash-locked in `LOCK.json`) and record it under "Changes made". The printable one-page sheet for the meeting
is [submission/clinician-review-questions.md](../submission/clinician-review-questions.md).

## What is being reviewed

### Pathway 1: `bp-elevated@1.0.0` (elevated blood pressure, scope MUST)
- **Trigger:** blood pressure screening with result "elevated".
- **Next action shown to staff:** "Repeat the measurement on another day. Hypertension is confirmed at 140 and/or
  90 mmHg or higher on two different days. Very high readings or symptoms go to the red-flag route."
- **Default deadline:** 7 days after the result (configurable default, pending clinical review).
- **Red flags:** no automatic threshold. `very_high_threshold` is **not set**; until a clinician sets it, a red
  flag comes only from the uploader, the patient or staff. A red flag pauses all automation (rule RF-1) and opens
  a human task; only a supervisor can resume automation.
- **Sources:** WHO hypertension fact sheet; WHO guideline for the pharmacological treatment of hypertension in
  adults (2021).
- **Patient message, Filipino (result notice, next step):** "ipasukat muli ang iyong presyon ng dugo sa ibang
  araw".

### Pathway 2: `cervical-abnormal@1.0.0` (abnormal cervical screen, scope SHOULD)
- **Trigger:** cervical screening with result "abnormal" or "positive".
- **Next action shown to staff:** "Colposcopy or clinician review, per risk".
- **Default deadline:** 30 days after the result (configurable default, pending clinical review).
- **Red flags:** none specific to this pathway; same human-reported red-flag route as above.
- **Sources:** USPSTF cervical cancer screening recommendation; ASCCP guidelines; Abu Dhabi DoH cervical cancer
  screening standard (2025). **No Philippine DOH guideline is cited yet**; the reviewer is asked which one to use.
- **Patient message, Filipino (result notice, next step):** "magpatingin sa clinician para sa follow-up na
  pagsusuri".

### Filipino patient messages used by both pathways (templates v1.0.0, pending native speaker review)
- **Result notice:** "Ang resulta ng iyong {screening_name} kamakailan ay nangangailangan ng susunod na hakbang.
  / Hindi ito diagnosis. Ibig sabihin nito, kailangan pang suriin ng isang health worker. / Susunod na hakbang:
  {next_step}. Pakigawa ito bago ang {due_date}. Matutulungan ka naming mag-book. / Kung masama ang pakiramdam mo
  o may bago o matinding sintomas, tumawag sa 911 o pumunta agad sa pinakamalapit na emergency room. Klinika:
  {clinic_phone}."
- **Reminder (SMS):** "Paalala mula sa iyong klinika: ang iyong follow-up ay dapat magawa bago ang {due_date}.
  Sumagot o tumawag sa {clinic_phone} kung kailangan mo ng tulong sa pag-book."
- **Emergency guidance:** "Kung ito ay emergency, tumawag agad sa 911 o pumunta sa pinakamalapit na emergency
  room. Naabisuhan na ang isang health worker at kokontakin ka niya. Klinika: {clinic_phone}."

Source files: `api/loopcloser/pathways/data/`, `api/loopcloser/templates/data/`.

## The 5 questions (same for both pathways)

1. **Is the next action right?** Is it what a rural health unit should do next for this result? What is missing
   or wrong?
2. **Is the deadline safe?** Is 7 days (blood pressure) / 30 days (cervical) safe as a default? What should it be,
   and should it depend on severity?
3. **Are the red flags complete?** What findings or symptoms must stop automation and go to a person at once?
   For blood pressure, what reading should count as "very high"?
4. **Is the Filipino message clear?** Would a patient understand it, and could it cause harm or panic? Suggested
   wording?
5. **What would stop you using this?** Anything that would make you refuse to use LoopCloser in your facility.

---

## Review record (copy this section once per reviewer)

| Field | Answer |
|---|---|
| Reviewer name | |
| Role and facility (e.g. physician, nurse, midwife; RHU or hospital) | |
| Licence or registration (optional) | |
| Date of review | |
| Pathways reviewed | ☐ bp-elevated@1.0.0 ☐ cervical-abnormal@1.0.0 |
| Permission to quote | ☐ Yes, with my name and role ☐ Yes, role only, no name ☐ No, do not quote |
| Exact words they agreed may be quoted (if any) | |

### bp-elevated@1.0.0
| # | Question | Answer |
|---|---|---|
| 1 | Is the next action right? | |
| 2 | Is the 7-day deadline safe? | |
| 3 | Are the red flags complete? (and the "very high" reading) | |
| 4 | Is the Filipino message clear? | |
| 5 | What would stop you using this? | |

### cervical-abnormal@1.0.0
| # | Question | Answer |
|---|---|---|
| 1 | Is the next action right? | |
| 2 | Is the 30-day deadline safe? | |
| 3 | Are the red flags complete? | |
| 4 | Is the Filipino message clear? | |
| 5 | What would stop you using this? | |

### Other comments

### Changes made because of this review
| Date | File and new version (e.g. `bp-elevated@1.0.1`) | What changed | Commit |
|---|---|---|---|
| | | | |

Sign-off status after this review: ☐ still pending ☐ approved with changes listed above ☐ approved as is
