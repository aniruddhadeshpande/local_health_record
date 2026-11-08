"""Anonymous inventory of samples/raw: prints only id, type, size, pages. Never names or content."""
import json, pathlib, sys
RAW = pathlib.Path(sys.argv[1])
SKIP = {"known_pii.txt", "expected_values.txt"}
out = []
for i, p in enumerate(sorted(f for f in RAW.iterdir() if f.is_file() and f.name not in SKIP), 1):
    head = p.read_bytes()[:8]
    kind = ("pdf" if head.startswith(b"%PDF") else "png" if head.startswith(b"\x89PNG") else
            "jpeg" if head.startswith(b"\xff\xd8") else "zip/xlsx" if head.startswith(b"PK") else
            "other:" + p.suffix.lower())
    info = {"id": f"S{i}", "kind": kind, "kb": p.stat().st_size // 1024}
    if kind == "pdf":
        import pypdfium2 as pdfium
        doc = pdfium.PdfDocument(str(p))
        info["pages"] = len(doc)
        info["text_chars_p1"] = len(doc[0].get_textpage().get_text_range().strip())
    out.append(info)
# map id -> real path kept LOCAL ONLY, outside anything printed
(RAW / ".id_map.json").write_text(json.dumps({o["id"]: str(f) for o, f in zip(out, sorted(f for f in RAW.iterdir() if f.is_file() and f.name not in SKIP and not f.name.startswith(".")))}))
print(json.dumps(out, indent=1))
for s in sorted(SKIP):
    f = RAW / s
    print(s, "present" if f.exists() else "MISSING", (f"{len(f.read_text().splitlines())} lines" if f.exists() else ""))
