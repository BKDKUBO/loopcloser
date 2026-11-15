"""Build the LoopCloser draft pitch deck. Figures come only from README.md and EVAL.md."""

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Inches, Pt

SCREENSHOTS = "/workspace/loopcloser/docs/screenshots/live/"
OUT = "/workspace/loopcloser/submission/LoopCloser-deck-DRAFT.pptx"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)

TEAL = RGBColor(0x0F, 0x76, 0x6E)
TEAL_SOFT = RGBColor(0xCC, 0xF0, 0xEC)
DARK = RGBColor(0x1F, 0x29, 0x37)
MUTED = RGBColor(0x4B, 0x55, 0x63)
RED = RGBColor(0xB9, 0x1C, 0x1C)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)
CARD_LINE = RGBColor(0xD1, 0xD5, 0xDB)


def _no_line(shape):
    shape.line.fill.background()


def _run(paragraph, text, size, color, bold=False):
    run = paragraph.runs[0] if paragraph.runs else paragraph.add_run()
    run.text = text
    run.font.size = Pt(size)
    run.font.color.rgb = color
    run.font.bold = bold
    run.font.name = "Carlito"
    return run


def _set_word_wrap(tf):
    tf.word_wrap = True
    # Keep text inside the box; do not shrink-to-fit, so overflow is visible on the render.
    tf.auto_size = None


def blank():
    s = prs.slides.add_slide(prs.slide_layouts[6])
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, Inches(0.12))
    bar.fill.solid()
    bar.fill.fore_color.rgb = TEAL
    _no_line(bar)
    return s


def add_textbox(slide, left, top, width, height):
    tf = slide.shapes.add_textbox(Inches(left), Inches(top), Inches(width), Inches(height)).text_frame
    _set_word_wrap(tf)
    return tf


def content_slide(title, bullets, img=None, kicker=None, note=None, size=None):
    s = blank()
    y_title = 0.28
    if kicker:
        tf = add_textbox(s, 0.6, 0.24, 12.1, 0.26)
        p = tf.paragraphs[0]
        p.text = ""
        _run(p, kicker, 12, TEAL, bold=True)
        y_title = 0.52
    tf = add_textbox(s, 0.6, y_title, 12.1, 0.64)
    p = tf.paragraphs[0]
    p.text = ""
    _run(p, title, 30, DARK, bold=True)

    body_top = 1.28 if kicker else 1.12
    body_h = 5.9 if kicker else 6.05
    body_w = 6.2 if img else 12.1
    font = size if size is not None else (16 if img else 18)
    space = 8 if img or size else 9

    tf = add_textbox(s, 0.6, body_top, body_w, body_h)
    for i, b in enumerate(bullets):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        placeholder = b.startswith("[")
        para.text = ""
        para.space_after = Pt(space)
        para.level = 0
        _run(para, ("" if placeholder else "\u2022 ") + b, font, RED if placeholder else DARK, bold=placeholder)
    if img:
        s.shapes.add_picture(SCREENSHOTS + img, Inches(7.05), Inches(body_top), width=Inches(5.7))
    return s


def criteria_map_slide():
    s = blank()
    tf = add_textbox(s, 0.5, 0.28, 12.3, 0.55)
    p = tf.paragraphs[0]
    p.text = ""
    _run(p, "How judges can assess LoopCloser", 30, DARK, bold=True)

    tf = add_textbox(s, 0.5, 0.88, 12.3, 0.42)
    p = tf.paragraphs[0]
    p.text = ""
    _run(
        p,
        "The six official Future Health judging parameters, as read out in the Hack2skill webinar on 4 November 2026.",
        14,
        MUTED,
    )

    cards = [
        (
            "1",
            "Health impact and clinical relevance",
            "Slides 3\u20134. Cited Philippine follow-up gap. No claim of improved outcomes, and no clinician sign-off yet.",
        ),
        (
            "2",
            "Technical depth and architecture",
            "Slide 8. Event-sourced cases, versioned pathways, 55/55 rule eval, ladder on vs off.",
        ),
        (
            "3",
            "Working solution and demonstration quality",
            "Slide 5. Live demo and 13 scripted cases, with screenshots. Demo video still a placeholder.",
        ),
        (
            "4",
            "Responsible AI, safety and data governance",
            "Slides 6\u20137. Rules decide. AI drafts only, for staff. A human reviews a result before any patient contact.",
        ),
        (
            "5",
            "Scalability and deployment readiness",
            "Slide 9. Live on Google Cloud, min 0 / max 1. Demo about US$0 to 2 per month.",
        ),
        (
            "6",
            "Commercial viability and path to pilot",
            "Slide 10. A 90-day RHU pilot is proposed, not agreed. About US$0.34\u20130.85 per facility per month.",
        ),
    ]

    margin, gutter, top = 0.5, 0.22, 1.42
    width = (13.333 - 2 * margin - 2 * gutter) / 3
    height = 2.35
    row_gap = 0.22
    for i, (num, title, body) in enumerate(cards):
        col, row = i % 3, i // 3
        left = margin + col * (width + gutter)
        y = top + row * (height + row_gap)
        card = s.shapes.add_shape(
            MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(y), Inches(width), Inches(height)
        )
        card.adjustments[0] = 0.08
        card.fill.solid()
        card.fill.fore_color.rgb = RGBColor(0xF7, 0xFB, 0xFA)
        card.line.color.rgb = CARD_LINE
        card.line.width = Pt(1)

        badge = s.shapes.add_shape(
            MSO_SHAPE.OVAL, Inches(left + 0.18), Inches(y + 0.18), Inches(0.38), Inches(0.38)
        )
        badge.fill.solid()
        badge.fill.fore_color.rgb = TEAL
        _no_line(badge)
        btf = badge.text_frame
        btf.word_wrap = False
        btf.auto_size = None
        btf.paragraphs[0].alignment = PP_ALIGN.CENTER
        btf.paragraphs[0].text = ""
        # Vertically centre the number in the circle as far as python-pptx allows.
        try:
            btf.paragraphs[0].space_before = Pt(2)
        except Exception:
            pass
        _run(btf.paragraphs[0], num, 14, WHITE, bold=True)

        tf = add_textbox(s, left + 0.66, y + 0.18, width - 0.84, 0.78)
        p = tf.paragraphs[0]
        p.text = ""
        _run(p, title, 14, DARK, bold=True)

        tf = add_textbox(s, left + 0.18, y + 1.00, width - 0.36, 1.20)
        p = tf.paragraphs[0]
        p.text = ""
        _run(p, body, 13, MUTED)

    tf = add_textbox(s, 0.5, 6.55, 12.3, 0.70)
    p = tf.paragraphs[0]
    p.text = ""
    _run(
        p,
        "Assumptions and limitations are on slide 11. Live demo, GitHub repo and the demo-video placeholder are on slide 12. "
        "Technical documentation is in the public repo.",
        13,
        MUTED,
    )
    return s


# 1. Cover
content_slide(
    "LoopCloser",
    [
        "Every result has a next action, an owner, a deadline, and a documented outcome.",
        "Team BKD KUBO. Future Health Digital Innovation Challenge, Challenge 05: Closing the Screening-to-Care Loop",
        "Live demo: https://loopcloser-bkdkubo.web.app (Demo mode, no sign-in)",
    ],
    img="02-today-supervisor.png",
)

# 2. Criteria map
criteria_map_slide()

# 3. Criterion 1 \u2014 problem
content_slide(
    "The problem",
    [
        "Screening only helps if an abnormal result leads to care. In the Philippines that step is where people are lost.",
        "CLAMS (DOH-supported cervical screening, Metro Manila): only 43% returned after screening, though 94% of those who returned were treated (APAC Women's Cancer Coalition, May 2024).",
        "Santo Tomas, Laguna rural audit (2013 to 2017): 73% of women with an abnormal result never returned (35 of 48) (Journal of Global Health Reports).",
        "34% of Filipino adults have hypertension; 49% of them did not know it; 48% controlled (PRESYON-5, 2026, PHA).",
        "We do not claim that LoopCloser has improved outcomes. There is no clinician sign-off and no pilot yet.",
        "[QUOTE: add a real nurse / BHW / patient quote with role and permission, or the published Paranaque health worker quote (Balikas News Network), labeled as a published interview]",
    ],
    kicker="Criterion 1 \u00b7 Health impact and clinical relevance",
    size=16,
)

# 4. Criterion 1 continued
content_slide(
    "Who it is for",
    [
        "The nurse or coordinator at a rural health unit with a stack of abnormal results and no way to see who has been reached, booked or lost.",
        "LoopCloser gives each result an owner and a deadline, shows who to call first and why, and escalates automatically when nobody follows up.",
    ],
    img="03-case-detail.png",
    kicker="Criterion 1 \u00b7 Health impact and clinical relevance",
)

# 5. Criterion 3
content_slide(
    "Working solution",
    [
        "Live demo: https://loopcloser-bkdkubo.web.app (Demo mode, no sign-in). Thirteen scripted stories (C-DEMO-01 to C-DEMO-13); screenshots in docs/screenshots/v2/.",
        "Today view: four lanes (needs action, overdue, waiting for patient, recently completed), highest priority first.",
        "\"Why this priority?\": every rule that fired, with its points. Escalation ladder: reminder, then community health worker, then supervisor.",
        "Timeline: every change is an event with the person, role and the rule that allowed it.",
    ],
    img="04-after-advance-3-days.png",
    kicker="Criterion 3 \u00b7 Working solution and demonstration quality",
)

# 6. Criterion 4
content_slide(
    "The safety line",
    [
        "Rules decide (versioned, cited pathways; published points table; no ML in any decision).",
        "A human reviews each result before any patient contact. Automation can only escalate or ask for human review.",
        "People close (reason plus evidence or sign-off; API refuses otherwise, rules CLOSE-1 and CLOSE-3).",
        "Red flags stop automation until a person resolves them.",
        "AI only drafts, for staff. Not a diagnostic AI.",
        "Honest note: all pathways pending clinical sign-off; the team has no clinician yet.",
    ],
    kicker="Criterion 4 \u00b7 Responsible AI, safety and data governance",
)

# 7. Criterion 4 continued
content_slide(
    "Where AI helps",
    [
        "Gemini 3.8 Flash on Vertex AI drafts a short call guide from masked facts (no names, phones or notes).",
        "Every number and date is checked against the case record; unmatched drafts are withheld.",
        "Use / Discard are logged; drafts never change state, priority, owner or deadline.",
        "Live: 2.7 to 3.6 s per draft, about US$0.001 per draft.",
    ],
    img="05-prepare-for-the-call.png",
    kicker="Criterion 4 \u00b7 Responsible AI, safety and data governance",
)

# 8. Criterion 2
content_slide(
    "Technical depth: measured, not estimated",
    [
        "55 of 55 labeled synthetic cases correct, 0 false positives, 0 false negatives. Guard rules 26/26: 0 unsafe actions allowed, 0 safe actions blocked.",
        "A conformance test against our own rules, not clinical accuracy. The eval caught 8 failures when two bugs were deliberately injected.",
        "Event-sourced cases, versioned hash-locked pathways, a published priority table, and an escalation ladder. API tests: 142 passed, 3 skipped (they need the Firestore emulator).",
        "Ladder on vs off, 1,018 synthetic cases, Day 14 (targets written before the run): T1 unaccountable and T2 silently overdue both went to 0; T3 and T4 unchanged, as targeted.",
        "T5 missed: 70.1% of reachable patients contacted, against a 90% target. The supervisor queue grew from 1 case to 379 (one person, no cap).",
    ],
    kicker="Criterion 2 \u00b7 Technical depth and architecture",
    size=17,
)

# 9. Criterion 5
content_slide(
    "Built on Google Cloud",
    [
        "Already live: Cloud Run (FastAPI, asia-southeast1), Firestore append-only event log, Firebase Hosting and Auth, Vertex AI (Gemini), Cloud Logging and Error Reporting.",
        "Default scale min 0, max 1 instance. Demo cost about US$0 to 2 per month; US$5 budget alert. About US$0.00002 database cost per patient lifecycle (14 writes, about 35 reads).",
        "Country setup (pathways, ladder days, message templates) is configuration, not code.",
        "Honest limits: only English and Filipino templates exist, and nothing has been tested outside the Philippines.",
    ],
    kicker="Criterion 5 \u00b7 Scalability and deployment readiness",
)

# 10. Criterion 6
content_slide(
    "A path to a pilot",
    [
        "A 90-day pilot at one rural health unit: a proposal, not an agreement. Real patients only after clinical sign-off of the pathways and templates.",
        "[TEAM TO CONFIRM any pilot partner before naming one]",
        "Cost per facility per month at Google Cloud list prices: about US$0.34 at 100 abnormal results, about US$0.85 at 300. SMS is not included (sending is simulated; no provider is chosen yet).",
        "Who could pay, as options only: the LGU or RHU operating budget, or PhilHealth. No discussion has taken place with either.",
        "Optional next step: Model Armor screening of AI prompts and drafts.",
    ],
    kicker="Criterion 6 \u00b7 Commercial viability and path to pilot",
    size=17,
)

# 11. Assumptions
content_slide(
    "Assumptions and limitations",
    [
        "All demo cases are synthetic (1,000 generated patients plus 13 scripted stories, labeled SIMULATED). Fictional cases are accepted for this challenge; they are not clinical evidence.",
        "No clinical pilot and no clinician validation yet. Pathways are pending sign-off.",
        "Ladder comparison, Day 14, 1,018 synthetic cases: 70.1% of reachable patients contacted, against a 90% target (T5).",
        "The supervisor queue grows to 379 cases with the ladder on (1 with it off): one person, no cap. Overdue cases stayed at 355 in both arms.",
        "Dashboard and Today numbers come from demo data, not a real facility.",
        "SMS cost is not priced. Sending is simulated; no provider is chosen yet.",
        "A human reviews each result before any patient contact. If nobody reviews a result, the ladder makes it visible but does not message the patient.",
        "We do not claim improved outcomes. Fuller notes: docs/assumptions-and-limitations.md.",
    ],
    size=16,
)

# 12. Team
def team_slide():
    s = blank()
    tf = add_textbox(s, 0.6, 0.28, 12.1, 0.64)
    p = tf.paragraphs[0]
    p.text = ""
    _run(p, "Team and links", 30, DARK, bold=True)

    logo = "/workspace/loopcloser/submission/assets/bkd-kubo-logo.jpg"
    # Native size 600 x 595. Keep the ratio; sit it on the right.
    logo_w = 3.4
    logo_h = logo_w * (595 / 600)
    s.shapes.add_picture(logo, Inches(9.2), Inches(1.55), width=Inches(logo_w), height=Inches(logo_h))

    lines = [
        # text, color, bold, size, space_after, bullet
        ("Team BKD KUBO", DARK, True, 22, 10, False),
        ("Manuel III Ocaña, Product Lead & Solution Architect", DARK, False, 20, 8, False),
        ("Elson Mojica, Domain Lead (Collections & Follow-up) & QA", DARK, False, 20, 22, False),
        ("Live demo: https://loopcloser-bkdkubo.web.app", DARK, False, 18, 8, True),
        ("GitHub: https://github.com/BKDKUBO/loopcloser", DARK, False, 18, 8, True),
        ("[Demo video link]", RED, True, 18, 8, False),
    ]
    tf = add_textbox(s, 0.6, 1.20, 8.2, 5.6)
    for i, (text, color, bold, size, space, bullet) in enumerate(lines):
        para = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        para.text = ""
        para.space_after = Pt(space)
        prefix = "\u2022 " if bullet else ""
        _run(para, prefix + text, size, color, bold=bold)
    return s

team_slide()

def _set_theme_font(name="Carlito"):
    """Use an installed face for the theme, so the deck does not depend on Calibri."""
    from lxml import etree

    ns = {"a": "http://schemas.openxmlformats.org/drawingml/2006/main"}
    seen = set()
    parts = [prs.part, * (m.part for m in prs.slide_masters)]
    for part in parts:
        for rel in part.rels.values():
            tgt = rel.target_part
            if tgt in seen:
                continue
            seen.add(tgt)
            partname = str(getattr(tgt, "partname", "") or "")
            if "theme" not in partname and "theme" not in str(rel.reltype):
                continue
            root = etree.fromstring(tgt.blob)
            for el in root.xpath(".//a:majorFont/a:latin | .//a:minorFont/a:latin", namespaces=ns):
                el.set("typeface", name)
            tgt._blob = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)

_set_theme_font()
prs.save(OUT)
print(OUT)
print("slides", len(prs.slides))
