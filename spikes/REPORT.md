# Q2 Spike: MedGemma 4B local extraction (2026-11-08)

## Setup
- **Model:** `medgemma:4b` from Ollama 0.34.2 (digest `9fe4e9a6c9bd`, gemma3 4.3B, Q4_K_M), temperature 0, `num_ctx` 8192, structured output via the Ollama `format` JSON schema.
- **Hardware:** 4-core CPU, 15.5 GB RAM, **no GPU**.
- **Samples:** synthetic, made by `spikes/make_synthetic_samples.py`, in `samples/synthetic/`. All identities are fictional. Each file has fake identifiers planted in its header, and R2 also has them inside a test name and a reference range.
- **Scripts:** `spikes/spike_extract.py` does the extraction, scoring, spike masking and guard. Raw results are in `spikes/out/results.json`.

## Results

| File | Route | Time | Values correct | Units | Ref ranges | Date | Masked leak check |
|---|---|---|---|---|---|---|---|
| BMI.xlsx | openpyxl text → MedGemma | 104 s | 6/6 rows | n/a | n/a | n/a | 0 hits |
| R1_text.pdf | text layer → MedGemma | 222 s | 12/12 | 12/12 | 12/12 | ✓ | 0 hits |
| R2_text.pdf (fake identifiers in fields) | text layer → MedGemma | 227 s | 12/12 | 12/12 | 12/12 | ✓ | 0 hits |
| R3_scan.jpg (skewed, noisy) | vision | 284 s | 12/12 | 10/12 | **0/12** | ✓ | 0 hits |
| R4_scan.pdf (image-only) | vision | 252 s | 12/12 | 10/12 | **0/12** | ✓ | 0 hits |

- **Numeric values: 54/54 (100%)** across every route.
- **Memory:** the Ollama `llama-server` runner uses **about 4.8 GB RSS** with the model loaded. Total system use was about 10.6 GB while other apps were also running.
- **Speed:** about 2 tokens/s for output. A one-page report takes **about 4 minutes** on this CPU, whether it goes through the text or vision route.

## Findings

1. **Values are reliable; everything around them on scans is not.** On the vision route MedGemma read every value correctly, but returned no reference ranges, got TSH's unit wrong (`ng/mL` instead of `uIU/mL`), and **made up H/L flags**: it marked WBC and TSH "L" when both were normal.
   → **Change:** never trust the flag MedGemma returns. Compute H/L locally from the value and the range. For vision-route files, take reference ranges and units from a local reference table, and mark those values "check this". This is a refinement of ticket 4.3, not a new requirement.
2. **Fake identifiers ended up in the wrong fields (security finding F1, confirmed).** On R2, MedGemma moved "Altanis method" and "Brightwell Diagnostics 3rd gen" into the `flag` field. The fixed set of allowed flag values dropped them. Without the strict field formats, the lab name would have reached Claude.
3. **Schema-first identifier capture is incomplete.** `patient_name` was empty in 3 of 4 reports, and `doctor_name` was **never** filled in. This didn't cause a leak, because only structured, format-checked fields are kept for sending. But the token mapping can't rely on the identifier fields alone.
   → **Change:** seed the known-value list from the profile, as the specs already say. Add a regex sweep of the raw page text for labelled header fields such as "Referred by:" and "Patient Name:", so the guard learns their values. This adds detail to ticket 5.3.
4. **The test-name normaliser was too strict.** "Vitamin D (25-OH)" was dropped from every masked report because of how the parentheses were stripped. The masking failed safe (dropped, not leaked), but data was lost.
   → **Change:** the local test-name list needs aliases. QA should count dropped fields.
5. **Speed is the main constraint.** At about 4 minutes per page, the 10 files × 10 pages limit could mean hours of processing. This supports the worker lease and argues for faster text routes.
   → **Recommendation:** keep MedGemma as the only reader (as the brief requires), but shorten the output. Have the model omit null identifier fields and drop the `flag` field, since flags are now computed locally. Measure again during apply. A GPU (about 2.3 GB of VRAM) would bring this down to seconds.
6. **Leak result: 0 fake-identifier hits** across all 5 masked outputs. The independent search covered all 15 known values plus their parts.

## Minimum hardware (measured)
- **CPU only:** a 4-core x86-64 machine with **8 GB RAM minimum** (about 4.8 GB for the model plus the API and OS). 16 GB is recommended. Expect about 4 minutes per page.
- **Optional GPU:** about 2.3–3 GB of VRAM for the Q4 build. GPU speed was not measured.
- **Disk:** 3.3 GB for the model.

## Limits of this spike
The samples are synthetic and cleanly laid out, while real lab reports vary much more. The vision-route results come from a single scanned layout. Re-run `spikes/spike_extract.py` against real, de-identified samples (in `samples/raw/`) before the demo.
