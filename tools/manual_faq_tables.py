"""Recover explicitly labelled question/answer columns with HTML span alignment."""
from __future__ import annotations

import re
from dataclasses import dataclass

from manual_faq_parser import Extraction, Pair, Rejected, clean


@dataclass(frozen=True, slots=True)
class Cell:
    text: str
    rows: int
    columns: int


def extract_tables(text: str) -> Extraction:
    pairs = []
    rejected = []
    for table in re.finditer(r'<table\b[^>]*>.*?</table>', text, re.DOTALL | re.IGNORECASE):
        if not re.search(r'질\s*[의문].*?답\s*변', table[0], re.DOTALL):
            continue
        origin = text.count('\n', 0, table.start()) + 1
        grid: dict[tuple[int, int], str] = {}
        question_column = answer_column = -1
        question = answer = ''
        first = last = 0
        current_number = ''
        table_pairs = []
        aligned = True
        for row_index, row in enumerate(re.finditer(r'<tr\b[^>]*>.*?</tr>', table[0], re.DOTALL | re.IGNORECASE)):
            line = origin + table[0].count('\n', 0, row.start())
            cells = []
            for cell in re.finditer(r'<t[dh]\b([^>]*)>(.*?)</t[dh]>', row[0], re.DOTALL | re.IGNORECASE):
                rowspan = re.search(r'rowspan=["\x27]?(\d+)', cell[1], re.IGNORECASE)
                colspan = re.search(r'colspan=["\x27]?(\d+)', cell[1], re.IGNORECASE)
                cells.append(Cell(clean(cell[2]), int(rowspan[1]) if rowspan else 1, int(colspan[1]) if colspan else 1))
            column = 0
            for cell in cells:
                while (row_index, column) in grid:
                    column += 1
                for down in range(cell.rows):
                    for across in range(cell.columns):
                        grid[row_index + down, column + across] = cell.text
                column += cell.columns
            values = [grid.get((row_index, index), '') for index in range(max(column, answer_column + 1))]
            labels = [re.sub(r'\s', '', value) for value in values]
            if '답변' in labels and ('질의' in labels or '질문' in labels):
                question_column = labels.index('질의') if '질의' in labels else labels.index('질문')
                answer_column = labels.index('답변')
                continue
            if question_column < 0 or len(values) <= answer_column:
                continue
            number = next((value for value in values[:question_column] if value.isdigit()), '')
            if (values[question_column] and not number
                    or any(value and value != values[answer_column] for value in values[answer_column + 1:])):
                aligned = False
            if number and number != current_number:
                if question and answer:
                    table_pairs.append(Pair(question, answer, first, first, last, '질의/답변 표', 'table_columns'))
                current_number = number
                question = answer = ''
                first = line
            if not current_number:
                continue
            qpart, apart = values[question_column], values[answer_column]
            if qpart and qpart not in question:
                question = (question + ' ' + qpart).strip()
            if apart and apart not in answer:
                answer = (answer + '\n' + apart).strip()
            last = line
        if question and answer:
            table_pairs.append(Pair(question, answer, first, first, last, '질의/답변 표', 'table_columns'))
        if aligned:
            pairs.extend(table_pairs)
        elif question_column >= 0:
            rejected.append(Rejected(origin, origin + table[0].count('\n'), '', 'table_split_question_or_extra_answer_columns'))
        if question_column < 0:
            rejected.append(Rejected(origin, origin + table[0].count('\n'), '', 'table_columns_without_header'))
    valid = []
    for pair in pairs:
        if len(pair.question) < 8 or len(pair.answer) < 15 or re.search(r'\b[QA]\d|OCR_LOW_CONF', pair.question + pair.answer):
            rejected.append(Rejected(pair.start_line, pair.end_line, pair.question, 'table_pair_requires_review'))
        else:
            valid.append(pair)
    return Extraction(tuple(valid), tuple(rejected))
