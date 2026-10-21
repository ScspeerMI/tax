# Working in the Fiscal Workbench

The user is a policy scholar fluent in economics but not in code or econometrics.
They ask questions in plain English; you run the model and explain the result.

## Running a score

- Use `.venv\Scripts\python score.py <measure> ...` (see README for the commands).
- Map the question onto a measure. If a proposal doesn't fit (a new bracket, a
  threshold change, a credit), say so plainly and offer to extend the model. Don't
  force it onto a measure that doesn't fit.
- Before answering, read the memo the run produced. Lead with the central estimate
  and the range, then name the one or two assumptions that drive the result.

## Ground rules

- Always report a range, not just the central case. Always state the static number alongside it.
- Never present a result as an official estimate. These are back-of-the-envelope
  checks built from published aggregates.
- Every new number or parameter goes in `assumptions.yaml` with a source. If you cannot
  source it, label it an assumption and say how confident you are.
- Don't invent elasticities or citations. If the literature is thin, say so in the
  source note.
- When you add a measure, give it its own caveats list (what could make it wrong) and,
  where one exists, a published benchmark to compare against.
- Sign convention: positive = more federal revenue; negative = a cost.

## Code layout

- `workbench/sources.py`: fetchers and the provenance cache (`data/raw/`).
- `workbench/distribution.py`: the taxable-income distribution built from CRA Table 2.
- `workbench/explorer.py`: the filer-level personal income tax engine (records + score).
- `workbench/model.py`: the measures; each returns a `Score`. PIT measures use explorer.py.
- `docs/`: the public web explorer. `docs/engine.js` is a line-for-line port of
  explorer.py; change both together and run `build_explorer.py`, which fails if they diverge.
  The explorer is presented as Sean's personal project, with no institutional branding.
- `workbench/report.py`: the chart, CSV and memo.
- `assumptions.yaml`: every parameter, with its source.
