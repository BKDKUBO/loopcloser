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
        path = img if img.startswith("/") else SCREENSHOTS + img
        s.shapes.add_picture(path, Inches(7.05), Inches(body_top), width=Inches(5.7))
    return s


def _arrow(slide, x1, y1, x2, y2, color=MUTED, dashed=False, width=1.75):
    from pptx.enum.shapes import MSO_CONNECTOR
    from lxml import etree

    c = slide.shapes.add_connector(MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2))
    c.line.color.rgb = color
    c.line.width = Pt(width)
    ln = c.line._get_or_add_ln()
    if dashed:
        dash = etree.SubElement(ln, qn("a:prstDash"))
        dash.set("val", "dash")
    tail = etree.SubElement(ln, qn("a:tailEnd"))
    tail.set("type", "triangle")
    tail.set("w", "med")
    tail.set("len", "med")
    return c


KIND_STYLE = {
    # kind: (fill, line, label)
    "fact": (RGBColor(0xEC, 0xFD, 0xF5), RGBColor(0x05, 0x96, 0x69), "RECORDED FACT"),
    "rule": (RGBColor(0xEF, 0xF6, 0xFF), RGBColor(0x25, 0x63, 0xEB), "RULE RESULT"),
    "human": (RGBColor(0xFF, 0xFB, 0xEB), RGBColor(0xB4, 0x53, 0x09), "A PERSON DECIDES"),
    "ai": (RGBColor(0xFA, 0xF5, 0xFF), RGBColor(0x7E, 0x22, 0xCE), "AI-WRITTEN (draft only)"),
    "hold": (RGBColor(0xFE, 0xF2, 0xF2), RGBColor(0xB9, 0x1C, 0x1C), "HELD"),
}


def _box(slide, left, top, width, height, title, body, kind, dashed=False):
    fill, line, label = KIND_STYLE[kind]
    b = slide.shapes.add_shape(MSO_SHAPE.ROUNDED_RECTANGLE, Inches(left), Inches(top), Inches(width), Inches(height))
    b.adjustments[0] = 0.1
    b.fill.solid()
    b.fill.fore_color.rgb = fill
    b.line.color.rgb = line
    b.line.width = Pt(2)
    if dashed:
        from lxml import etree

        dash = etree.SubElement(b.line._get_or_add_ln(), qn("a:prstDash"))
        dash.set("val", "dash")
    tf = b.text_frame
    tf.word_wrap = True
    tf.auto_size = None
    tf.vertical_anchor = MSO_ANCHOR.TOP
    for m in ("margin_left", "margin_right"):
        setattr(tf, m, Inches(0.08))
    tf.margin_top = Inches(0.06)
    p = tf.paragraphs[0]
    p.text = ""
    p.alignment = PP_ALIGN.LEFT
    _run(p, title, 13, DARK, bold=True)
    p2 = tf.add_paragraph()
    p2.text = ""
    _run(p2, body, 11, MUTED)
    p3 = tf.add_paragraph()
    p3.text = ""
    _run(p3, label, 10, line, bold=True)
    return b


def workflow_slide():
    """Each step of the workflow and exactly where AI sits (same content as the README mermaid diagram)."""
    s = blank()
    tf = add_textbox(s, 0.5, 0.24, 12.3, 0.26)
    p = tf.paragraphs[0]
    p.text = ""
    _run(p, "How it works", 12, TEAL, bold=True)
    tf = add_textbox(s, 0.5, 0.48, 12.3, 0.6)
    p = tf.paragraphs[0]
    p.text = ""
    _run(p, "Each step, and exactly where AI sits: drafting only. People decide.", 28, DARK, bold=True)

    w, h, gap = 2.75, 1.45, 0.42
    x0, y1, y2 = 0.5, 1.5, 4.25
    xs = [x0 + i * (w + gap) for i in range(4)]
    _box(s, xs[0], y1, w, h, "1. Result uploaded", "CSV import, checked row by row before anything is saved", "fact")
    _box(s, xs[1], y1, w, h, "2. Rules route it", "Versioned pathway sets next action and deadline; published points set priority", "rule")
    _box(s, xs[2], y1, w, h, "3. A person reviews the result", "Nothing reaches the patient before this (ladder Day 1)", "human")
    _box(s, xs[3], y1, w, h, "4. Checks before contact", "Consent, phone, result on file, owner, red flag: each Pass or Hold (GATE-1)", "rule")
    for i in range(3):
        _arrow(s, xs[i] + w, y1 + h / 2, xs[i + 1], y1 + h / 2)

    # Hold branch, between the rows, to the left of the Pass arrow
    hold_x, hold_y, hold_w, hold_h = xs[2] + 0.2, y1 + h + 0.15, w + 0.05, 1.12
    _box(s, hold_x, hold_y, hold_w, hold_h, "Hold: no call, no SMS",
         "Staff record what is missing; the checks run again (demo: C-DEMO-14)", "hold")
    _arrow(s, xs[3] + 0.35, y1 + h, hold_x + hold_w, hold_y + hold_h / 2, color=RED)

    # Row 2, right to left: 5, 6, 7
    x5, x6, x7 = xs[3], xs[2], xs[1]
    _box(s, x5, y2 + 0.15, w, h, "5. Staff contact the patient", "Call, approved SMS template, or home visit. Pass only.", "human")
    _box(s, x6, y2 + 0.15, w, h, "6. Booked, visit recorded", "Appointment and visit are events in the log", "fact")
    _box(s, x7, y2 + 0.15, w, h, "7. Closed by a coordinator", "Reason plus evidence (visit date, facility, record) or sign-off", "human")
    _arrow(s, xs[3] + w / 2, y1 + h, xs[3] + w / 2, y2 + 0.15, color=RGBColor(0x05, 0x96, 0x69))
    tfp = add_textbox(s, xs[3] + w / 2 + 0.08, y1 + h + 0.5, 1.4, 0.3)
    _run(tfp.paragraphs[0], "All pass", 12, RGBColor(0x05, 0x96, 0x69), bold=True)
    _arrow(s, x5, y2 + 0.15 + h / 2, x6 + w, y2 + 0.15 + h / 2)
    _arrow(s, x6, y2 + 0.15 + h / 2, x7 + w, y2 + 0.15 + h / 2)

    # AI box: the only AI in the product, feeding step 5 as a draft
    _box(s, x0, y2 + 0.15, w, h + 0.2, "Optional call guide",
         "Gemini drafts it for staff from masked facts; every number and date is checked. Use or Discard is logged.",
         "ai", dashed=True)
    _arrow(s, x0 + w / 2, y2 + 0.15, x0 + w / 2, y2 - 0.25, color=RGBColor(0x7E, 0x22, 0xCE), dashed=True)
    tfa = add_textbox(s, x0, y2 - 0.75, w + 0.4, 0.5)
    _run(tfa.paragraphs[0], "read before the call (step 5); never sent, never changes the case", 11,
         RGBColor(0x7E, 0x22, 0xCE), bold=True)

    tf = add_textbox(s, 0.5, 6.45, 12.3, 0.8)
    p = tf.paragraphs[0]
    p.text = ""
    _run(p, "Also running: the escalation ladder (Day 2 to 14: reminder, which is gated; home visit; supervisor) and red "
         "flags, which stop all automation until a person takes over. The case page labels every item as Recorded "
         "fact, Rule result or AI-written.", 13, MUTED)
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
            "Slides 4\u20135. Cited Philippine follow-up gap. No claim of improved outcomes, and no clinician sign-off yet.",
        ),
        (
            "2",
            "Technical depth and architecture",
            "Slide 9. Event-sourced cases, versioned pathways, 55/55 rule eval, ladder on vs off.",
        ),
        (
            "3",
            "Working solution and demonstration quality",
            "Slide 6. Live demo and 14 scripted cases, with screenshots. Demo video still a placeholder.",
        ),
        (
            "4",
            "Responsible AI, safety and data governance",
            "Slides 2, 7\u20138. Rules decide; AI drafts only, for staff. Content labels and pass/hold checks. WHO and DECIDE-AI mapping.",
        ),
        (
            "5",
            "Scalability and deployment readiness",
            "Slide 10. Live on Google Cloud, min 0 / max 1. Demo about US$0 to 2 per month.",
        ),
        (
            "6",
            "Commercial viability and path to pilot",
            "Slide 11. A 90-day RHU pilot is proposed, not agreed; evidence plan written. About US$0.34\u20130.85 per facility per month.",
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
        "Assumptions and limitations are on slide 12. Live demo, GitHub repo and the demo-video placeholder are on slide 13. "
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

# 2. Workflow: each step and where AI sits
workflow_slide()

# 3. Criteria map
criteria_map_slide()

# 4. Criterion 1 \u2014 problem
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

# 5. Criterion 1 continued
content_slide(
    "Who it is for",
    [
        "The nurse or coordinator at a rural health unit with a stack of abnormal results and no way to see who has been reached, booked or lost.",
        "LoopCloser gives each result an owner and a deadline, shows who to call first and why, and escalates automatically when nobody follows up.",
    ],
    img="03-case-detail.png",
    kicker="Criterion 1 \u00b7 Health impact and clinical relevance",
)

# 6. Criterion 3
content_slide(
    "Working solution",
    [
        "Live demo: https://loopcloser-bkdkubo.web.app (Demo mode, no sign-in). Fourteen scripted stories (C-DEMO-01 to C-DEMO-14); screenshots in docs/screenshots/v2/.",
        "Today view: four lanes (needs action, overdue, waiting for patient, recently completed), highest priority first.",
        "\"Why this priority?\": every rule that fired, with its points. Escalation ladder: reminder, then community health worker, then supervisor.",
        "Timeline: every change is an event with the person, role and the rule that allowed it.",
    ],
    img="04-after-advance-3-days.png",
    kicker="Criterion 3 \u00b7 Working solution and demonstration quality",
)

# 7. Criterion 4
content_slide(
    "The safety line",
    [
        "Rules decide; a human reviews each result before any patient contact; people close with evidence or sign-off (CLOSE-1, CLOSE-3).",
        "Checks before contact: consent, phone, result on file, owner, red flag, each Pass or Hold. Calls and SMS are blocked on Hold (GATE-1). Demo: C-DEMO-14 (right).",
        "Every item on a case is labeled Recorded fact, Rule result or AI-written. Staff can download the summary and audit trail; downloads are logged.",
        "Red flags stop automation. AI only drafts, for staff. Not a diagnostic AI.",
        "Mapped to WHO's six AI-for-health principles and DECIDE-AI (docs/frameworks.md): a self-assessment, not an external review.",
        "Honest note: all pathways pending clinical sign-off; the team has no clinician yet.",
    ],
    img="/workspace/loopcloser/submission/assets/case-gates-on-hold.png",
    kicker="Criterion 4 \u00b7 Responsible AI, safety and data governance",
    size=15,
)

# 8. Criterion 4 continued
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

# 9. Criterion 2
content_slide(
    "Technical depth: measured, not estimated",
    [
        "55 of 55 labeled synthetic cases correct, 0 false positives, 0 false negatives. Guard rules 26/26: 0 unsafe actions allowed, 0 safe actions blocked.",
        "A conformance test against our own rules, not clinical accuracy. The eval caught 8 failures when two bugs were deliberately injected.",
        "Event-sourced cases, versioned hash-locked pathways, a published priority table, and an escalation ladder. API tests: 154 passed, 3 skipped (they need the Firestore emulator); web tests: 18 passed.",
        "Ladder on vs off, 1,019 synthetic cases, Day 14 (targets written before the run): T1 unaccountable and T2 silently overdue both went to 0; T3 and T4 unchanged, as targeted.",
        "T5 missed: 70.0% of reachable patients contacted, against a 90% target. The supervisor queue grew from 1 case to 380 (one person, no cap).",
    ],
    kicker="Criterion 2 \u00b7 Technical depth and architecture",
    size=17,
)

# 10. Criterion 5
content_slide(
    "Built on Google Cloud",
    [
        "Already live: Cloud Run (FastAPI, asia-southeast1), Firestore append-only event log, Firebase Hosting and Auth, Vertex AI (Gemini), Cloud Logging and Error Reporting.",
        "Default scale min 0, max 1 instance. Demo cost about US$0 to 2 per month; US$5 budget alert. About US$0.00002 database cost per patient lifecycle (14 writes, about 35 reads).",
        "Country setup (pathways, ladder days, message templates) is configuration, not code.",
        "Honest limits: only English and Filipino templates exist, and nothing has been tested outside the Philippines.",
        "Future integration targets: Malaffi, Oracle Health and Epic. No integration exists today; results come in by CSV.",
    ],
    kicker="Criterion 5 \u00b7 Scalability and deployment readiness",
)

# 11. Criterion 6
content_slide(
    "A path to a pilot",
    [
        "A 90-day pilot at one rural health unit: a proposal, not an agreement. Real patients only after clinical sign-off of the pathways and templates.",
        "[TEAM TO CONFIRM any pilot partner before naming one]",
        "Cost per facility per month at Google Cloud list prices: about US$0.34 at 100 abnormal results, about US$0.85 at 300. SMS is not included (sending is simulated; no provider is chosen yet).",
        "Who could pay, as options only: the LGU or RHU operating budget, or PhilHealth. No discussion has taken place with either.",
        "Evidence plan (a plan, not done): first compare outputs against cases a clinician already knows, then measure contact, completion, holds and AI draft use (docs/pilot-evidence-plan.md).",
    ],
    kicker="Criterion 6 \u00b7 Commercial viability and path to pilot",
    size=17,
)

# 12. Assumptions
content_slide(
    "Assumptions and limitations",
    [
        "All demo cases are synthetic (1,000 generated patients plus 14 scripted stories, labeled SIMULATED). Fictional cases are accepted for this challenge; they are not clinical evidence.",
        "No clinical pilot and no clinician validation yet. Pathways are pending sign-off.",
        "Ladder comparison, Day 14, 1,019 synthetic cases: 70.0% of reachable patients contacted, against a 90% target (T5).",
        "The supervisor queue grows to 380 cases with the ladder on (1 with it off): one person, no cap. Overdue cases stayed at 355 in both arms.",
        "Dashboard and Today numbers come from demo data, not a real facility.",
        "SMS cost is not priced. Sending is simulated; no provider is chosen yet.",
        "A human reviews each result before any patient contact. If nobody reviews a result, the ladder makes it visible but does not message the patient.",
        "We do not claim improved outcomes. Fuller notes: docs/assumptions-and-limitations.md.",
    ],
    size=16,
)

# 13. Team
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
