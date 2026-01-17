# ================= PDF (HINDI SAFE VERSION) =================
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import lightgrey

# Register Hindi Font
pdfmetrics.registerFont(
    TTFont("Hindi", "NotoSansDevanagari-Regular.ttf")
)

def generate_pdf(uid, exam, topic, attempts, score, total):
    file = f"result_{uid}.pdf"
    doc = SimpleDocTemplate(
        file,
        pagesize=A4,
        rightMargin=36,
        leftMargin=36,
        topMargin=36,
        bottomMargin=36
    )

    styles = getSampleStyleSheet()

    styles.add(ParagraphStyle(
        name="Hindi",
        fontName="Hindi",
        fontSize=11,
        leading=15
    ))

    styles.add(ParagraphStyle(
        name="HindiTitle",
        fontName="Hindi",
        fontSize=16,
        leading=20,
        spaceAfter=15
    ))

    story = []

    # Header
    story.append(Paragraph("📘 MyScoreCard – टेस्ट परिणाम", styles["HindiTitle"]))
    story.append(Paragraph(f"परीक्षा : {exam}", styles["Hindi"]))
    story.append(Paragraph(f"विषय : {topic}", styles["Hindi"]))
    story.append(Paragraph(f"स्कोर : {score} / {total}", styles["Hindi"]))
    story.append(Spacer(1, 20))

    # Questions
    for i, a in enumerate(attempts, 1):
        story.append(Paragraph(f"<b>प्रश्न {i} :</b> {a['question']}", styles["Hindi"]))
        story.append(Spacer(1, 5))

        for opt, val in a["options"].items():
            story.append(Paragraph(f"{opt}. {val}", styles["Hindi"]))

        story.append(Spacer(1, 5))
        story.append(Paragraph(f"<b>सही उत्तर :</b> {a['correct']}", styles["Hindi"]))
        story.append(Paragraph(f"<b>व्याख्या :</b> {a['explanation']}", styles["Hindi"]))
        story.append(Spacer(1, 15))

    # Watermark
    def watermark(canvas, doc):
        canvas.saveState()
        canvas.setFont("Hindi", 30)
        canvas.setFillColor(lightgrey)
        canvas.translate(300, 400)
        canvas.rotate(45)
        canvas.drawCentredString(0, 0, "MyScoreCard Bot")
        canvas.restoreState()

    doc.build(story, onFirstPage=watermark, onLaterPages=watermark)
    return file
