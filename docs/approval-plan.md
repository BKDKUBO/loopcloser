# Plan: items that need approval before they happen

Written 2026-11-09 (Manila) after comparing LoopCloser with AI Builder Cup finalists.

**Status, 2026-11-09 11:59 PM Manila:** items 1 to 4 were approved and are **live**. Gemini 3.8 Flash is not
offered in Vertex AI asia-southeast1, so it runs from the `global` location. The old Gemini API key secret is
still in Secret Manager but no longer used by Cloud Run. Items 5 to 10 still need a yes (or the team). Prices are list
prices checked on 2026-11-09; confirm on the linked pages before enabling.

Dates: Hack2skill early review submission Nov 15, feedback by Nov 17, final Nov 20.

| # | Item | Effort | Cost | Impact on judging | Recommendation |
|---|---|---|---|---|---|
| 1 | ✅ Done. Deploy the `finalist-polish` web change (safety line on sign-in and case pages) | 15 min | About US$0 (Hosting and Cloud Build free tiers) | Medium: the safety line becomes visible in the live demo | **Do before Nov 15** |
| 2 | ✅ Done. Show AI where it does real work: a staff-only "Prepare for the call" draft on the case page (case facts, open barriers, which approved template fits), with Use / Discard, logged as an event | 4 to 6 h | Gemini calls only, see #3 | High: today the judged demo shows no AI at all | **Do before Nov 15**, staff-only, never patient-facing |
| 3 | ✅ Done. Move Gemini from the AI Studio key to Vertex AI (service account, no API key) | 2 to 3 h, enables `aiplatform.googleapis.com` | Gemini 3.8 Flash on Vertex: US$0.75 / US$3.75 per 1M input / output tokens through Dec 31, 2026, then US$1.50 / US$7.50 ([Vertex pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)). A draft of about 400 input and 100 output tokens is about US$0.0007, so about US$0.70 per 1,000 drafts | Medium: matches what finalists showed; removes a long-lived API key | Do together with #2 |
| 4 | ✅ Done. Check every AI draft before showing it: every date, number and state in the draft must appear in the case fields, otherwise it is not shown | 2 h, code only | US$0 | Medium: "cited facts verified" on screen | **Do with #2** (no new API) |
| 5 | Model Armor screening of AI prompts and drafts | 2 to 3 h, enables `modelarmor.googleapis.com` | Free up to 2M tokens per month, then US$0.10 per 1M ([Model Armor](https://cloud.google.com/security/products/model-armor)). Demo use stays far below 2M, so about US$0 | Low to medium: good safety story, only worth it if #2 ships | Optional, after #2 |
| 6 | Grounding with Google Search | 1 to 2 h | 5,000 grounded queries per month free, then US$14 per 1,000 ([Vertex pricing](https://cloud.google.com/vertex-ai/generative-ai/pricing)) | Low. Case drafts must use only the case record; web search adds risk, not value | **Skip** |
| 7 | ADK agent with tools | 1 to 2 days | Gemini calls as in #3 | Low, and it works against "rules decide" | **Skip**; explain why in the README instead |
| 8 | Keep one API instance warm during a judging window (min 1) to avoid the 10 s cold start | 5 min each way | Idle min instance about US$0.0000025 per vCPU-second plus US$0.0000025 per GiB-second ([Cloud Run pricing](https://cloud.google.com/run/pricing)); 1 vCPU and 512 MiB is about US$0.32 per day, so about US$1 for Nov 15 to 17 | Medium if judges open the demo cold | Manuel is handling Nov 15 to 17 with his own schedules; the deployed service stays at min 0 |
| 9 | Re-record the video (under 3 min) and add the deck link | 1 to 2 h, the team | US$0 | High: finalists put the video and deck at the top | **Team to do before Nov 15** |
| 10 | Real user quote (nurse, barangay health worker or patient), with role and permission | The team | US$0 | High: every strong finalist had one real person | **Team to do**; the README has a marked placeholder |

## Notes
- Gemini key: billed on the key's own project, not `loopcloser-bkdkubo`. Moving to Vertex (#3) puts AI cost in
  `loopcloser-bkdkubo`, under its US$5/month budget alert.
- A budget alert does not stop spending. Max 1 Cloud Run instance is the real compute cap.
- No item changes any decision rule. AI stays drafts-only, staff-only, labeled, and out of every guard rule.
