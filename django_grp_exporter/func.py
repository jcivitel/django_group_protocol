import copy
import io
import re

from pypdf import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, Spacer, SimpleDocTemplate, PageBreak
from reportlab.platypus import TableStyle
from datetime import datetime


def process_mentions(text):
    """
    Process @mentions in text to format them.
    Finds patterns like @FirstName or @FirstName_LastName and formats them.
    Returns the processed text with HTML formatting.
    """
    if not text:
        return text
    
    # Pattern to match @mentions (word characters and underscores)
    pattern = r'@(\w+(?:_\w+)*)'
    
    def format_mention(match):
        mention = match.group(1).replace('_', ' ')
        return f'<b><u>{mention}</u></b>'
    
    return re.sub(pattern, format_mention, text)


def gen_export(protocol, template="django_grp_exporter/docs/letterhead_blank.pdf"):
    """
    Generate a comprehensive PDF export with cover page, table of contents,
    attendance list, and protocol entries.
    """
    template_path = template
    
    # Try to open template, fall back if not exists
    try:
        template_reader = PdfReader(template_path)
        has_template = True
    except:
        has_template = False
        template_reader = None

    overlay_stream = io.BytesIO()
    pdf = SimpleDocTemplate(overlay_stream)
    styles = getSampleStyleSheet()
    
    # Create custom styles
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#333333'),
        spaceAfter=30,
        alignment=1,  # Center alignment
    )
    
    heading_style = ParagraphStyle(
        'CustomHeading',
        parent=styles['Heading2'],
        fontSize=14,
        textColor=colors.HexColor('#555555'),
        spaceAfter=12,
    )

    story = []
    toc_entries = []

    # ============ COVER PAGE ============
    story.append(Spacer(1, 1 * inch))
    story.append(Paragraph(f"Protokoll", title_style))
    story.append(Paragraph(f"Gruppe: {protocol.group.name}", styles["Heading2"]))
    story.append(Spacer(1, 0.2 * inch))
    story.append(
        Paragraph(
            f"Protokoll vom {protocol.protocol_date.strftime('%d.%m.%Y')}",
            styles["Normal"]
        )
    )
    story.append(Spacer(1, 0.3 * inch))
    story.append(
        Paragraph(
            f"Erstellt am: {datetime.now().strftime('%d.%m.%Y %H:%M')}",
            styles["Normal"]
        )
    )
    story.append(Spacer(1, 0.5 * inch))
    story.append(
        Paragraph(
            f"{protocol.group.get_full_address()}".replace("\n", "<br/>"),
            styles["Normal"]
        )
    )
    story.append(PageBreak())

    # ============ TABLE OF CONTENTS PAGE ============
    toc_start_index = len(story)
    story.append(Paragraph("Inhaltsverzeichnis", heading_style))
    story.append(Spacer(1, 0.2 * inch))
    
    # Placeholder for TOC entries (will be filled later)
    toc_placeholder_index = len(story)
    story.append(Spacer(1, 0.1 * inch))
    
    story.append(PageBreak())

    # ============ ATTENDANCE LIST PAGE ============
    story.append(Paragraph("Anwesenheitsliste", heading_style))
    story.append(Spacer(1, 0.1 * inch))
    
    presence_data = [["Mitarbeiter", "Anwesend"]]
    for presence in protocol.protocolpresence_set.all():
        name = (
            presence.user.get_full_name()
            if presence.user.get_full_name()
            else presence.user.username
        )
        presence_data.append([name, "✓ Ja" if presence.was_present else "✗ Nein"])
    
    presence_table = Table(presence_data, colWidths=[3.5 * inch, 1.5 * inch])
    presence_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor('#4472C4')),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.whitesmoke),
                ("ALIGN", (0, 0), (-1, 0), "CENTER"),
                ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
                ("FONTSIZE", (0, 0), (-1, 0), 11),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 1, colors.HexColor('#CCCCCC')),
                ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor('#F0F0F0')]),
                ("ALIGN", (1, 1), (-1, -1), "CENTER"),
            ]
        )
    )
    story.append(presence_table)
    story.append(Spacer(1, 0.3 * inch))
    story.append(PageBreak())

    # ============ PROTOCOL ITEMS PAGE ============
    story.append(Paragraph("Protokollpunkte", heading_style))
    story.append(Spacer(1, 0.2 * inch))
    
    items = protocol.items.all()
    for idx, item in enumerate(items, 1):
        # Add TOC entry
        toc_entry = Paragraph(f"{idx}. {item.name}", styles["Normal"])
        toc_entries.append(toc_entry)

        # Add item heading and content
        story.append(Paragraph(f"{idx}. {item.name}", styles["Heading3"]))
        
        # Process mentions in the value
        processed_value = process_mentions(item.value or "")
        if processed_value:
            story.append(
                Paragraph(
                    processed_value.replace("\n", "<br/>"),
                    styles["Normal"],
                )
            )
        else:
            story.append(Paragraph("Keine Details", styles["Normal"]))
        
        story.append(Spacer(1, 0.15 * inch))

    # ============ INSERT TABLE OF CONTENTS ============
    # Replace the placeholder with actual TOC entries
    if toc_entries:
        story[toc_placeholder_index:toc_placeholder_index+1] = toc_entries + [Spacer(1, 0.2 * inch)]

    # Build PDF
    pdf.build(story)

    overlay_stream.seek(0)
    overlay_reader = PdfReader(overlay_stream)
    writer = PdfWriter()

    # Add all pages from generated PDF
    for idx, overlay_page in enumerate(overlay_reader.pages):
        # Only use template for first page if available
        if has_template and template_reader and idx == 0:
            try:
                merged_page = copy.deepcopy(template_reader.pages[0])
                merged_page.merge_page(overlay_page)
                writer.add_page(merged_page)
            except:
                # Fallback if template has issues
                writer.add_page(overlay_page)
        else:
            # For all other pages, just add the page as-is
            writer.add_page(overlay_page)

    output_stream = io.BytesIO()
    writer.write(output_stream)
    output_stream.seek(0)

    return output_stream
