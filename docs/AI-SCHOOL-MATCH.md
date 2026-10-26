# AI School Match

`/school-match` — 7 questions (city/area/PIN, grade, boards, budget band, school type/co-ed/medium, up to 5 priorities). **No child data is asked for or stored.**

**Scoring** (`tse/lib/match.py`): location 22, grade 16, board 14, budget 16, priorities 10, gender 6, medium 6, type 6, trust 4 (verification + verified parent reviews). Unknown information scores neutral. Payment never changes a score; sponsored schools appear only in a separate, labelled sidebar.

**Detailed reasons** (fees within budget, transport, class size, support) are hidden until the parent unlocks that school — this drives the ₹499 unlock pack. Schools on Plus/Pro share their verified detailed profile with the matcher; Basic schools are matched on public data ("Matched on public information only").

**AI advisor:** with `ANTHROPIC_API_KEY` set, Claude writes a short, neutral summary with visit questions using only school names, match scores and public reasons (no parent contact data). Without a key, a template summary is used.

Results feed shortlists, side-by-side compare (detailed rows locked until unlocked), school dashboards ("AI School Match appearances") and the Growth desk (demand by city & grade). Also available to the app via `POST /api/v1/school-match`.
