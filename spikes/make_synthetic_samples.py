"""Generate synthetic health samples with planted canary PII + ground truth.

Outputs (in OUT dir):
  R1_text.pdf     digital blood report (text layer)
  R2_text.pdf     later digital blood report; canaries also in a test name and a reference range
  R3_scan.jpg     scanned/photographed version of a third report (no text layer, skewed, noisy)
  R4_scan.pdf     image-only PDF of R3 (scanned PDF route)
  BMI.xlsx        dated height/weight/BMI rows, with canary header rows
  ground_truth.json, known_pii.txt

All people, IDs and organisations are fictional.
Run: uv run --no-project --with fpdf2,openpyxl,pypdfium2,pillow python -I spikes/make_synthetic_samples.py samples/synthetic
"""
import json
import pathlib
import random
import sys

from fpdf import FPDF
from openpyxl import Workbook
from PIL import Image, ImageFilter
import pypdfium2 as pdfium

OUT = pathlib.Path(sys.argv[1])
OUT.mkdir(parents=True, exist_ok=True)
random.seed(7)

PII = {
    "name": "Zorvan Quillbeck",
    "mrn": "MRN-7731-ZQX",
    "dob": "14/03/1987",
    "phone": "+91 90000 47321",
    "email": "zorvan.q@example.test",
    "address": "42 Larkspur Lane, Pune 411001",
    "lab": "Brightwell Diagnostics",
    "doctor": "Dr. Meera Altanis",
}
SAMPLE_IDS = {"R1": "SMP-55819", "R2": "SMP-61204", "R3": "SMP-70377"}

# (test, unit, ref range, values for R1, R2, R3)
TESTS = [
    ("Hemoglobin", "g/dL", "13.0-17.0", 13.8, 13.1, 12.6),
    ("WBC Count", "10^3/uL", "4.0-11.0", 7.2, 8.1, 9.4),
    ("Platelet Count", "10^3/uL", "150-410", 245, 230, 212),
    ("Fasting Glucose", "mg/dL", "70-100", 98, 106, 112),
    ("HbA1c", "%", "4.0-5.6", 5.6, 5.9, 6.2),
    ("Total Cholesterol", "mg/dL", "0-200", 192, 208, 221),
    ("LDL Cholesterol", "mg/dL", "0-100", 118, 129, 141),
    ("HDL Cholesterol", "mg/dL", "40-60", 46, 43, 41),
    ("Triglycerides", "mg/dL", "0-150", 140, 162, 175),
    ("Creatinine", "mg/dL", "0.7-1.3", 0.9, 1.0, 1.0),
    ("TSH", "uIU/mL", "0.4-4.0", 2.1, 2.4, 2.8),
    ("Vitamin D (25-OH)", "ng/mL", "30-100", 24, 27, 31),
]
DATES = {"R1": "2026-02-10", "R2": "2026-05-18", "R3": "2026-09-02"}
IDX = {"R1": 3, "R2": 4, "R3": 5}


def flag(val, rng):
    lo, hi = (float(x) for x in rng.split("-"))
    return "H" if val > hi else "L" if val < lo else ""


def report_pdf(rid, path, canary_in_fields=False):
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 15)
    pdf.cell(0, 8, PII["lab"].upper(), new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", size=9)
    pdf.cell(0, 5, f"{PII['address']}  |  Ph: {PII['phone']}", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(3)
    pdf.set_font("Helvetica", size=10)
    header = [
        ("Patient Name", PII["name"]), ("Patient ID", PII["mrn"]),
        ("DOB", PII["dob"]), ("Age/Sex", "39 Y / Male"),
        ("Sample ID", SAMPLE_IDS[rid]), ("Collected", DATES[rid]),
        ("Referred by", PII["doctor"]), ("Email", PII["email"]),
    ]
    for i in range(0, len(header), 2):
        for k, v in header[i:i + 2]:
            pdf.cell(95, 6, f"{k}: {v}")
        pdf.ln(6)
    pdf.ln(3)
    pdf.set_font("Helvetica", "B", 10)
    for h, w in (("Test", 70), ("Result", 25), ("Unit", 30), ("Reference Range", 45), ("Flag", 15)):
        pdf.cell(w, 7, h, border=1)
    pdf.ln(7)
    pdf.set_font("Helvetica", size=10)
    for t in TESTS:
        name, unit, rng, val = t[0], t[1], t[2], t[IDX[rid]]
        shown_name, shown_rng = name, rng
        if canary_in_fields and name == "TSH":
            shown_name = f"TSH ({PII['lab']} 3rd gen)"
        if canary_in_fields and name == "Hemoglobin":
            shown_rng = f"{rng} (Altanis method)"
        for txt, w in ((shown_name, 70), (str(val), 25), (unit, 30), (shown_rng, 45), (flag(val, rng), 15)):
            pdf.cell(w, 7, txt, border=1)
        pdf.ln(7)
    pdf.ln(4)
    pdf.set_font("Helvetica", "I", 9)
    pdf.multi_cell(0, 5, f"Impression: Reviewed by {PII['doctor']}. Mild dyslipidaemia; correlate clinically. "
                         f"Contact {PII['phone']} for queries.")
    pdf.output(str(path))


def scan_from_pdf(pdf_path, jpg_path, scan_pdf_path):
    page = pdfium.PdfDocument(str(pdf_path))[0]
    img = page.render(scale=2).to_pil().convert("L")
    img = img.rotate(1.8, expand=True, fillcolor=235).filter(ImageFilter.GaussianBlur(0.8))
    px = img.load()
    w, h = img.size
    for _ in range(w * h // 60):  # salt noise
        x, y = random.randrange(w), random.randrange(h)
        px[x, y] = random.choice((40, 200))
    img.save(jpg_path, quality=70)
    img.convert("RGB").save(scan_pdf_path, "PDF", resolution=144)


def bmi_xlsx(path):
    wb = Workbook()
    ws = wb.active
    ws.title = "BMI Log"
    ws.append(["Name", PII["name"]])
    ws.append(["Member ID", PII["mrn"]])
    ws.append(["Clinic", PII["lab"]])
    ws.append([])
    ws.append(["Date", "Height (cm)", "Weight (kg)", "BMI"])
    rows = [("2026-01-05", 176, 84.0), ("2026-03-02", 176, 85.2), ("2026-04-28", 176, 86.1),
            ("2026-06-30", 176, 84.7), ("2026-08-25", 176, 83.5), ("2026-10-20", 176, 82.4)]
    out = []
    for d, hcm, wkg in rows:
        bmi = round(wkg / (hcm / 100) ** 2, 1)
        ws.append([d, hcm, wkg, bmi])
        out.append({"date": d, "height_cm": hcm, "weight_kg": wkg, "bmi": bmi})
    wb.save(path)
    return out


report_pdf("R1", OUT / "R1_text.pdf")
report_pdf("R2", OUT / "R2_text.pdf", canary_in_fields=True)
report_pdf("R3", OUT / "_R3_src.pdf")
scan_from_pdf(OUT / "_R3_src.pdf", OUT / "R3_scan.jpg", OUT / "R4_scan.pdf")
(OUT / "_R3_src.pdf").unlink()
bmi_rows = bmi_xlsx(OUT / "BMI.xlsx")

truth = {"pii": PII, "sample_ids": SAMPLE_IDS, "files": {}}
for rid, fname in (("R1", "R1_text.pdf"), ("R2", "R2_text.pdf"), ("R3", "R3_scan.jpg"), ("R3", "R4_scan.pdf")):
    truth["files"][fname] = {
        "date": DATES[rid],
        "tests": [{"name": t[0], "value": t[IDX[rid]], "unit": t[1], "ref": t[2]} for t in TESTS],
    }
truth["files"]["BMI.xlsx"] = {"measurements": bmi_rows}
(OUT / "ground_truth.json").write_text(json.dumps(truth, indent=1))
(OUT / "known_pii.txt").write_text("\n".join(list(PII.values()) + list(SAMPLE_IDS.values()) + ["1987-03-14", "Altanis", "Quillbeck"]) + "\n")
print("wrote", sorted(p.name for p in OUT.iterdir()))
