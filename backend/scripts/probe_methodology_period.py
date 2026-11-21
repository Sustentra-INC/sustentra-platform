"""Run the Methodology prefill's reporting-period rules against a real document, without Claude or a database.

    python -m backend.scripts.probe_methodology_period path/to/statement.pdf [--year 2024]

The document is read by the same parser the pipeline uses (``ParserService``), turned into the same numbered
lines the prefill sends, and then every line that could carry the period is tried:

* lines that print a date or a year wording ("year ended", "calendar year", "twelve months ended"): what dates
  were read, whether the quote would be called one year, and the basis its words give;
* the first lines of the document: which one ``title_year`` takes as the title for the year, and which
  other line stops it (a second year, a sentence, a "Prepared ..." opening).

Nothing but line numbers and rule names is printed for a line unless ``--show`` is given, so the output of a
confidential document can be shared; the public statements this was written for need no such care.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from backend.app.services import methodology_prefill as mp
from backend.app.services import methodology_review as rules
from backend.app.services.ai_locator import document_lines, norm
from backend.app.services.parser_service import ParserService


def main(argv: list[str] | None = None) -> int:
    args = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    args.add_argument("path", type=Path)
    args.add_argument("--year", type=int, help="the reporting year to test the title rule for (default: the title's own)")
    args.add_argument("--show", action="store_true", help="print the text of each line")
    options = args.parse_args(argv)
    output = ParserService().parse_document(file_path=str(options.path), document_id="probe", processing_run_id="probe",
                                            mime_type=None)
    lines = document_lines(output)
    print(f"{len(lines)} lines read (parser status: {output.get('status')})")

    def shown(text: str) -> str:
        return f"  {text[:160]!r}" if options.show else ""

    print("\n-- lines that could carry the period --")
    for line in lines:
        text = line.text
        dates = sorted(mp.dates_in(text))
        wording = mp.basis_in_words(text)
        cue = mp._YEAR_CUES.search(mp.match_text(text)) is not None
        if not (dates and cue) and wording is None:
            continue
        if not dates:
            print(f"{line.alias} page={line.page_number}: no date, basis={wording}{shown(text)}")
        for end in dates:
            print(f"{line.alias} page={line.page_number}: dates={[d.isoformat() for d in dates]} "
                  f"year_wording={mp.states_a_year(text, end)} basis={wording} "
                  f"start_would_be={rules.year_start_for(end)}{shown(text)}")

    print("\n-- the title rule (first 15 lines) --")
    head = lines[: mp.TITLE_LINES]
    for line in head:
        folded = norm(line.text)
        prints_year = mp._TITLE_YEAR.search(folded) is not None
        dated = mp._DATE_LINE.search(folded) is not None
        found_year = mp.title_year(lines, line)
        want = f" want={options.year}" if options.year else ""
        print(f"{line.alias}: prints_a_year={prints_year} dating_line={dated} sentence_end={line.text.strip().endswith(('.', '!', '?'))} "
              f"title_year={found_year}{want}{shown(line.text)}")
    if not any(mp.title_year(lines, line) for line in head):
        print("no first-15-lines line is taken as a title: the first one printing a year must be that line alone, with "
              "no sentence end and no other year (cover dates excepted) on the other lines")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
