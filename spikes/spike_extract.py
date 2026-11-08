"""Q2 spike: MedGemma 4B extraction accuracy + masking leak check on synthetic samples.

Routes: text PDF -> pypdfium2 text -> MedGemma (text)
        scanned JPG / image-only PDF -> PNG <=1600px -> MedGemma (vision)
        XLSX -> openpyxl rows -> MedGemma (text)  [+ deterministic baseline]
Run: uv run --no-project --with httpx,pypdfium2,pillow,openpyxl,rapidfuzz python -I spikes/spike_extract.py samples/synthetic spikes/out
"""
import base64
import io
import json
import pathlib
import re
import subprocess
import sys
import threading
import time

import httpx
import pypdfium2 as pdfium
from openpyxl import load_workbook
from PIL import Image
from rapidfuzz import fuzz

SRC, OUT = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
OUT.mkdir(parents=True, exist_ok=True)
OLLAMA = "http://127.0.0.1:11434/api/chat"
MODEL = "medgemma:4b"

IDENT = {k: {"type": ["string", "null"]} for k in
         ("patient_name", "patient_id", "dob", "sample_id", "lab_name", "doctor_name", "phone", "email", "address", "report_date")}
SCHEMA_REPORT = {"type": "object", "properties": {**IDENT, "tests": {"type": "array", "items": {
    "type": "object", "properties": {"name": {"type": "string"}, "value": {"type": ["number", "string"]},
                                     "unit": {"type": ["string", "null"]}, "ref_range": {"type": ["string", "null"]},
                                     "flag": {"type": ["string", "null"]}},
    "required": ["name", "value"]}}}, "required": ["tests"]}
SCHEMA_BMI = {"type": "object", "properties": {**IDENT, "measurements": {"type": "array", "items": {
    "type": "object", "properties": {"date": {"type": "string"}, "height_cm": {"type": "number"},
                                     "weight_kg": {"type": "number"}, "bmi": {"type": "number"}},
    "required": ["date", "weight_kg"]}}}, "required": ["measurements"]}

PROMPT = ("You are a medical data extraction engine. Extract every field from this {what} into the JSON schema. "
          "Put identifiers (patient name, IDs, date of birth, lab/hospital name, doctor, phone, email, address) ONLY "
          "in their identifier fields. Copy numbers exactly as printed. report_date as YYYY-MM-DD. "
          "Do not invent values; use null if absent.\n\n{body}")


# ---------- peak RAM sampler (ollama runner RSS) ----------
peak = {"mb": 0}
stop = threading.Event()


def sample_rss():
    while not stop.is_set():
        try:
            out = subprocess.run(["ps", "-C", "ollama", "-o", "rss="], capture_output=True, text=True).stdout
            mb = sum(int(x) for x in out.split()) // 1024
            peak["mb"] = max(peak["mb"], mb)
        except Exception:
            pass
        time.sleep(0.5)


def png_bytes(img: Image.Image) -> bytes:
    img = img.convert("RGB")
    img.thumbnail((1600, 1600))
    buf = io.BytesIO()
    img.save(buf, "PNG")
    return buf.getvalue()


def ask(prompt, schema, images=()):
    body = {"model": MODEL, "stream": False, "format": schema, "options": {"temperature": 0, "num_ctx": 8192},
            "messages": [{"role": "user", "content": prompt,
                          **({"images": [base64.b64encode(i).decode() for i in images]} if images else {})}]}
    t = time.time()
    r = httpx.post(OLLAMA, json=body, timeout=1800)
    r.raise_for_status()
    return json.loads(r.json()["message"]["content"]), time.time() - t


def extract(path: pathlib.Path):
    if path.suffix == ".xlsx":
        rows = [[c for c in r if c is not None] for r in load_workbook(path, read_only=True).active.iter_rows(values_only=True)]
        text = "\n".join(" | ".join(str(c) for c in r) for r in rows if r)
        return "text", ask(PROMPT.format(what="BMI spreadsheet", body=text), SCHEMA_BMI)
    if path.suffix == ".pdf":
        doc = pdfium.PdfDocument(str(path))
        text = "\n".join(doc[i].get_textpage().get_text_range() for i in range(len(doc))).strip()
        if len(text) > 50:
            return "text", ask(PROMPT.format(what="blood test report", body=text), SCHEMA_REPORT)
        imgs = [png_bytes(doc[i].render(scale=2).to_pil()) for i in range(len(doc))]
        return "vision", ask(PROMPT.format(what="scanned blood test report image", body=""), SCHEMA_REPORT, imgs)
    return "vision", ask(PROMPT.format(what="scanned blood test report image", body=""), SCHEMA_REPORT,
                         [png_bytes(Image.open(path))])


def num(v):
    try:
        return float(re.sub(r"[^\d.\-]", "", str(v)))
    except ValueError:
        return None


def score(fname, got, truth):
    t = truth["files"][fname]
    if "measurements" in t:
        exp, rows = t["measurements"], got.get("measurements", [])
        ok = sum(any(r.get("date") == e["date"] and num(r.get("weight_kg")) == e["weight_kg"]
                     and num(r.get("bmi")) == e["bmi"] for r in rows) for e in exp)
        return {"expected": len(exp), "correct": ok, "extra_rows": max(0, len(rows) - len(exp))}
    exp, tests = t["tests"], got.get("tests", [])
    ok_val = ok_unit = ok_ref = found = 0
    misses = []
    for e in exp:
        m = max(tests, key=lambda x: fuzz.token_set_ratio(e["name"], str(x.get("name", ""))), default=None)
        if not m or fuzz.token_set_ratio(e["name"], str(m.get("name", ""))) < 80:
            misses.append(f"{e['name']}: not found")
            continue
        found += 1
        if num(m.get("value")) == float(e["value"]):
            ok_val += 1
        else:
            misses.append(f"{e['name']}: got {m.get('value')} want {e['value']}")
        ok_unit += str(m.get("unit") or "").replace(" ", "").lower() == e["unit"].replace(" ", "").lower()
        ok_ref += e["ref"].replace(" ", "") in str(m.get("ref_range") or "").replace(" ", "")
    date_ok = got.get("report_date") == t["date"]
    return {"expected": len(exp), "found": found, "value_correct": ok_val, "unit_correct": ok_unit,
            "ref_contains_truth": ok_ref, "date_ok": date_ok, "misses": misses}


# ---------- masking (spike version of design: schema-first + rules + format constraints) ----------
UNITS = {"g/dl", "10^3/ul", "mg/dl", "%", "uiu/ml", "ng/ml", "mmol/l", "iu/l", "u/l", "pg/ml", "fl", "pg", "10^6/ul"}
RANGE = re.compile(r"^\s*([<>]=?\s*)?\d+(\.\d+)?(\s*-\s*\d+(\.\d+)?)?\s*$")
KNOWN_TESTS = {"hemoglobin", "wbc count", "platelet count", "fasting glucose", "hba1c", "total cholesterol",
               "ldl cholesterol", "hdl cholesterol", "triglycerides", "creatinine", "tsh", "vitamin d (25-oh)"}
PATTERNS = [re.compile(p) for p in (r"\+?\d[\d\s-]{8,}\d", r"[\w.]+@[\w.]+", r"\b[A-Z]{2,4}-\d{3,}", r"\d{1,2}/\d{1,2}/\d{4}")]


def anchor_offset(date, anchor="2026-01-05"):
    from datetime import date as D
    try:
        return f"T0{(D.fromisoformat(date) - D.fromisoformat(anchor)).days:+d}d"
    except Exception:
        return None


def mask(got, known):
    dropped = []

    def clean_name(n):
        base = re.sub(r"\s*\(.*?\)", "", n).strip()
        best = max(KNOWN_TESTS, key=lambda k: fuzz.ratio(k, base.lower()))
        if fuzz.ratio(best, base.lower()) >= 85:
            return best
        dropped.append("test_name")
        return None

    out = {"date": anchor_offset(got.get("report_date") or "")}
    if "tests" in got:
        out["tests"] = []
        for t in got["tests"]:
            name = clean_name(str(t.get("name", "")))
            ref = str(t.get("ref_range") or "")
            ref_m = re.match(r"^\s*([\d.]+\s*-\s*[\d.]+)", ref)
            unit = str(t.get("unit") or "").strip()
            rec = {"name": name, "value": num(t.get("value")),
                   "unit": unit if unit.lower().replace(" ", "") in UNITS else None,
                   "ref": ref_m.group(1) if ref_m and RANGE.match(ref_m.group(1)) else None,
                   "flag": t.get("flag") if t.get("flag") in ("H", "L", "") else None}
            if name:
                out["tests"].append(rec)
    if "measurements" in got:
        out["measurements"] = [{"date": anchor_offset(m.get("date", "")), "weight_kg": num(m.get("weight_kg")),
                                "height_cm": num(m.get("height_cm")), "bmi": num(m.get("bmi"))}
                               for m in got["measurements"]]
    blob = json.dumps(out)
    for k in known:  # guard: exact + fuzzy on tokens + patterns
        if k.lower() in blob.lower() or fuzz.partial_ratio(k.lower(), blob.lower()) >= 90 and len(k) > 6:
            raise ValueError("guard hit")
    for p in PATTERNS:
        if p.search(blob):
            raise ValueError(f"pattern hit {p.pattern}")
    return out, dropped


def ident_capture(got, truth):
    pii = truth["pii"]
    fields = {"patient_name": pii["name"], "patient_id": pii["mrn"], "lab_name": pii["lab"], "doctor_name": pii["doctor"]}
    return {f: bool(got.get(f)) and fuzz.partial_ratio(v.lower(), str(got.get(f)).lower()) >= 85 for f, v in fields.items()}


truth = json.loads((SRC / "ground_truth.json").read_text())
known = [l for l in (SRC / "known_pii.txt").read_text().splitlines() if l.strip()]
threading.Thread(target=sample_rss, daemon=True).start()
results = {}
for f in ["BMI.xlsx", "R1_text.pdf", "R2_text.pdf", "R3_scan.jpg", "R4_scan.pdf"]:
    print(f"-> {f}", flush=True)
    try:
        route, (got, secs) = extract(SRC / f)
    except Exception as e:  # keep going
        results[f] = {"error": repr(e)[:200]}
        print("   error", e, flush=True)
        continue
    (OUT / f"{f}.extracted.json").write_text(json.dumps(got, indent=1))
    res = {"route": route, "seconds": round(secs, 1), "accuracy": score(f, got, truth)}
    if "tests" in got:
        res["identifiers_captured"] = ident_capture(got, truth)
    try:
        masked, dropped = mask(got, known)
        (OUT / f"{f}.masked.json").write_text(json.dumps(masked, indent=1))
        res["mask"] = {"guard": "pass", "dropped_fields": dropped}
    except ValueError as e:
        res["mask"] = {"guard": f"BLOCKED ({e})"}
    results[f] = res
    print("  ", json.dumps(res), flush=True)
stop.set()
results["_peak_ollama_rss_mb"] = peak["mb"]
(OUT / "results.json").write_text(json.dumps(results, indent=1))
print("peak ollama RSS MB:", peak["mb"])
