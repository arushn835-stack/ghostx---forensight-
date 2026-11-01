import json
from datetime import datetime, timezone
from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer, Table,
                                TableStyle)
from xml.sax.saxutils import escape

from models import AnalysisResult, Evidence, EvidenceRelation, HandlingLog, InvestigationTask
from services.contamination_analysis import analyze_handling_events


def build_case_report(case):
    output = BytesIO()
    doc = SimpleDocTemplate(output, pagesize=letter, rightMargin=0.62 * inch,
                            leftMargin=0.62 * inch, topMargin=0.65 * inch,
                            bottomMargin=0.65 * inch, title=f"Case report: {case.case_number}")
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="SmallCell", parent=styles["BodyText"], fontSize=7.5, leading=9, alignment=TA_LEFT, wordWrap="CJK"))
    styles.add(ParagraphStyle(name="SectionHeading", parent=styles["Heading2"], textColor=colors.HexColor("#a26a00"), spaceBefore=14, spaceAfter=6))
    story = [Paragraph("FORENSIGHT | CASE RECORD", styles["Title"]),
             _paragraph(f"Case {case.case_number}: {case.title}", styles["Heading2"]),
             Paragraph(f"Generated {datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')} | Investigator: {case.investigator.username}", styles["BodyText"]),
             Spacer(1, 8)]
    metadata = [["Case type", case.case_type], ["Status", case.status], ["Priority", case.priority], ["Description", case.description or "Not recorded"]]
    story.append(Table(metadata, colWidths=[1.25 * inch, 5.85 * inch], style=TableStyle([
        ("BACKGROUND", (0, 0), (0, -1), colors.HexColor("#ece9e1")),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#d0cdc5")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 6),
    ])))
    story.append(Paragraph("Evidence inventory", styles["SectionHeading"]))
    evidence = Evidence.query.filter_by(case_id=case.id).order_by(Evidence.evidence_number).all()
    rows = [["ID / Category", "Description / filename", "SHA-256"]]
    for item in evidence:
        rows.append([
            _paragraph(f"{item.evidence_number}<br/>{item.category}", styles["SmallCell"]),
            _paragraph(f"{item.description or 'No description'}<br/>{item.original_filename}", styles["SmallCell"]),
            _paragraph(item.sha256_hash, styles["SmallCell"]),
        ])
    if len(rows) == 1:
        rows.append(["No evidence records", "", ""])
    story.append(Table(rows, colWidths=[1.3 * inch, 3.2 * inch, 2.6 * inch], repeatRows=1, style=TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#292c2b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white), ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c9c6be")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 5),
    ])))
    tasks = InvestigationTask.query.filter_by(case_id=case.id).order_by(InvestigationTask.created_at).all()
    story.append(Paragraph("Investigation checklist", styles["SectionHeading"]))
    story.append(_simple_table([["Task", "Status", "Priority", "Due"]] + [
        [task.title, task.status, task.priority, task.due_date.isoformat() if task.due_date else "Not set"] for task in tasks
    ] or [["Task", "Status", "Priority", "Due"], ["No tasks recorded", "", "", ""]], styles))
    relations = EvidenceRelation.query.filter_by(case_id=case.id).all()
    story.append(Paragraph("Recorded evidence relationships", styles["SectionHeading"]))
    relation_rows = [["Evidence pair", "Relationship", "Origin / review"]]
    relation_rows.extend([[f"{rel.source.evidence_number} -> {rel.target.evidence_number}", rel.relationship_type,
                           f"{rel.source_type} / {rel.verification_status}"] for rel in relations])
    if len(relation_rows) == 1:
        relation_rows.append(["No relationships recorded", "", ""])
    story.append(_simple_table(relation_rows, styles, [2.0 * inch, 2.7 * inch, 2.4 * inch]))
    story.append(Paragraph("Handling history and screening prompts", styles["SectionHeading"]))
    events = HandlingLog.query.filter_by(case_id=case.id).order_by(HandlingLog.created_at).all()
    if events:
        event_rows = [["Evidence", "Event / time", "Custody and notes"]]
        for event in events:
            event_rows.append([event.evidence.evidence_number,
                               f"{event.action}<br/>{event.event_timestamp.isoformat() if event.event_timestamp else 'Timestamp not recorded'}",
                               f"{event.previous_custodian} -> {event.new_custodian}<br/>{event.notes or event.recorded_location}"])
        story.append(_simple_table(event_rows, styles, [1.1 * inch, 2.2 * inch, 3.8 * inch]))
    else:
        story.append(Paragraph("No handling events recorded.", styles["BodyText"]))
    warnings = []
    for item in evidence:
        item_events = HandlingLog.query.filter_by(evidence_id=item.id).order_by(HandlingLog.created_at.asc()).all()
        for warning in analyze_handling_events(item_events):
            warnings.append(f"{item.evidence_number}: {warning['rule']} · {warning['review_status']} · {warning['explanation']}")
    if warnings:
        story.extend(Paragraph(text, styles["BodyText"]) for text in warnings)
    else:
        story.append(Paragraph("No configured handling documentation prompts were found. This is not a compliance determination.", styles["BodyText"]))
    story.append(Paragraph("Recorded image metadata and analysis results", styles["SectionHeading"]))
    analyses = AnalysisResult.query.filter_by(case_id=case.id).order_by(AnalysisResult.created_at).all()
    if analyses:
        for analysis in analyses:
            story.append(_paragraph(f"{analysis.analysis_type} | {analysis.model_name} | Review: {analysis.review_status}<br/>{json.dumps(json.loads(analysis.result_json), ensure_ascii=True)}<br/>Metadata only; not a forensic interpretation.", styles["BodyText"]))
    else:
        story.append(Paragraph("No analysis records. No object detection or specialized forensic AI results are represented.", styles["BodyText"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("This report compiles records stored in ForenSight. Automated screening items are prompts for human review, not findings. Investigative conclusions remain with authorized personnel.", styles["Italic"]))
    doc.build(story, onFirstPage=_page_number, onLaterPages=_page_number)
    output.seek(0)
    return output


def _simple_table(rows, styles, widths=None):
    widths = widths or [1.75 * inch, 1.75 * inch, 1.4 * inch, 1.7 * inch]
    table = Table([[_paragraph(value, styles["SmallCell"]) for value in row] for row in rows], colWidths=widths, repeatRows=1)
    table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#292c2b")),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("GRID", (0, 0), (-1, -1), 0.35, colors.HexColor("#c9c6be")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"), ("PADDING", (0, 0), (-1, -1), 5),
    ]))
    return table


def _paragraph(value, style):
    return Paragraph("<br/>".join(escape(part) for part in str(value).split("<br/>")), style)


def _page_number(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#5b5e5c"))
    canvas.drawString(doc.leftMargin, 0.38 * inch, "FORENSIGHT | WORKING CASE RECORD")
    canvas.drawRightString(letter[0] - doc.rightMargin, 0.38 * inch, f"Page {doc.page}")
    canvas.restoreState()