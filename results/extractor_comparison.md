# Intake extractor comparison (synthetic notes)

40 invented referral notes × 8 required fields. *Unsafe* = a value proposed as extracted that differs from the label; *missed* = left for the clinician although the note states it. Every proposal still goes through clinician confirmation.

LLM extractor: not measured in this run (no API key). Run with `--llm` to add it.

## all

| Extractor | Correct | Unsafe | Missed |
|---|---|---|---|
| rule-based | 92.2% (295/320) | 0 | 25 |

## written with the rules (n01–n30)

| Extractor | Correct | Unsafe | Missed |
|---|---|---|---|
| rule-based | 99.2% (238/240) | 0 | 2 |

## varied phrasing (n31–n40)

| Extractor | Correct | Unsafe | Missed |
|---|---|---|---|
| rule-based | 71.2% (57/80) | 0 | 23 |
