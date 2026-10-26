# How the form definitions were produced
`original_uploads/` holds your Word forms. `docx2lines.py` extracts them (including table cells and checkboxes); `parse_forms.py` / `qparse.py` convert question-style forms automatically; forms with irregular layouts were transcribed into the compact `dsl/*.form` format (`dsl.py`); `merge.py` cleans up, assigns directory categories and DPDP visibility tiers and writes `../tse/forms/*.json`.
You don't need these tools to change a form — edit the JSON and import it from Admin → Registration forms. They're kept for traceability.
