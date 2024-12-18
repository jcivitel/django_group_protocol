import copy
import io

from PyPDF2 import PdfReader, PdfWriter
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
from reportlab.platypus import Paragraph, Table, Spacer, SimpleDocTemplate, PageBreak
from reportlab.platypus import TableStyle


def gen_export(protocol, template="media/docs/letterhead_blank.pdf"):
    template_path = template
    template_reader = PdfReader(template_path)

    overlay_stream = io.BytesIO()
    pdf = SimpleDocTemplate(overlay_stream)
    styles = getSampleStyleSheet()

    story = []
    toc_entries = []

    story.append(
        Paragraph(f"Protokoll für die Gruppe {protocol.group.name}", styles["Title"])
    )
    story.append(Paragraph(f"Datum: {protocol.protocol_date}", styles["Normal"]))
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph("Anwesenheitsliste:", styles["Heading2"]))
    story.append(Spacer(1, 0.1 * inch))
    presence_data = [["Mitarbeiter", "Anwesend?"]]
    for presence in protocol.protocolpresence_set.all():
        presence_data.append(
            [
                (
                    presence.user.get_full_name()
                    if presence.user.get_full_name()
                    else presence.user.username
                ),
                "Ja" if presence.was_present else "Nein",
            ]
        )
    presence_table = Table(presence_data, hAlign="LEFT")
    presence_table.setStyle(
        TableStyle(
            [
                ("BACKGROUND", (0, 0), (-1, 0), colors.grey),
                ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
                ("ALIGN", (0, 0), (0, 0), "CENTER"),
                ("FONTNAME", (0, 0), (0, 0), "Helvetica-Bold"),
                ("BOTTOMPADDING", (0, 0), (-1, 0), 12),
                ("BACKGROUND", (0, 1), (-1, -1), colors.white),
                ("GRID", (0, 0), (-1, -1), 1, colors.black),
            ]
        )
    )
    story.append(presence_table)
    story.append(Spacer(1, 0.2 * inch))

    story.append(Paragraph(f"Gruppeninfo:", styles["Heading3"]))
    story.append(Paragraph(f"{protocol.group.name}", styles["Normal"]))
    story.append(Paragraph(f"{protocol.group.get_full_address()}", styles["Normal"]))
    story.append(Spacer(1, 0.4 * inch))

    c = canvas.Canvas(overlay_stream)

    story.append(Paragraph("Protokollpunkte:", styles["Heading2"]))
    for item in protocol.items.all():
        toc_entry = Paragraph(
            f"{item.name} .......... {c.getPageNumber()}", styles["Normal"]
        )
        toc_entries.append(toc_entry)

        story.append(Paragraph(item.name, styles["Heading3"]))
        story.append(
            Paragraph(
                f"{item.value or 'Keine Details'}".replace("\n", "<br/>"),
                styles["Normal"],
            )
        )
        story.append(Spacer(1, 0.1 * inch))

    story[10:0] = (
        [Paragraph("Inhaltsverzeichnis:", styles["Heading2"]), Spacer(1, 12)]
        + toc_entries
        + [PageBreak()]
    )

    pdf.build(story, canvasmaker=canvas.Canvas)

    overlay_stream.seek(0)
    overlay_reader = PdfReader(overlay_stream)
    writer = PdfWriter()

    for overlay_page in overlay_reader.pages:
        merged_page = copy.deepcopy(template_reader.pages[0])
        merged_page.merge_page(overlay_page)
        writer.add_page(merged_page)

    output_stream = io.BytesIO()
    writer.write(output_stream)
    output_stream.seek(0)

    return output_stream
