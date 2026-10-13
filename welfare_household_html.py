"""Project HTML values only through explicit, unique household columns."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class HouseholdCell:
    household: int
    value: str
    label: str
    unit: str
    row: int
    column: int


@dataclass(frozen=True, slots=True)
class Cell:
    text: str
    row_span: int
    col_span: int


ROW = re.compile(r'<tr\b[^>]*>(.*?)</tr>', re.IGNORECASE | re.DOTALL)
CELL = re.compile(r'<t[dh]\b([^>]*)>(.*?)</t[dh]>', re.IGNORECASE | re.DOTALL)
UNIT = re.compile(r'단위\s*[:：]\s*(만원|천원|원)')
COUNT = re.compile(r'(\d{1,2})\s*인(?:\s*가구)?')


def _text(fragment: str) -> str:
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', fragment)).strip()


def _span(attributes: str, name: str) -> int:
    match = re.search(rf'\b{name}\s*=\s*["\']?(\d+)', attributes, re.IGNORECASE)
    return int(match[1]) if match else 1


def household_cells(table: str, caption_unit: str = '') -> tuple[HouseholdCell, ...]:
    """Expand declared spans; reject a value spanning two household headers.

    Empty OCR margin cells can overlap an empty span. Nonempty overlaps, duplicate
    household headers, missing units and conflicting geometry yield no facts.
    A label-only row can continue into the immediately following parenthetic row.
    """
    occupied: dict[int, tuple[Cell, int]] = {}
    headers: dict[int, int] = {}
    caption = ''
    pending_label = ''
    unit = caption_unit
    facts: list[HouseholdCell] = []
    for row_number, row_match in enumerate(ROW.finditer(table), start=1):
        occupied = {col: value for col, value in occupied.items() if value[1] >= row_number}
        grid = {col: value[0] for col, value in occupied.items()}
        placed: list[tuple[int, Cell]] = []
        column = 0
        for match in CELL.finditer(row_match[1]):
            cell = Cell(_text(match[2]), _span(match[1], 'rowspan'), _span(match[1], 'colspan'))
            if not (1 <= cell.row_span <= 64 and 1 <= cell.col_span <= 64):
                return ()
            while column in grid:
                column += 1
            if column + cell.col_span > 64:
                return ()
            span = range(column, column + cell.col_span)
            if any(col in grid and grid[col].text for col in span):
                return ()
            placed.append((column, cell))
            for col in span:
                grid[col] = cell
                if cell.row_span > 1:
                    occupied[col] = (cell, row_number + cell.row_span - 1)
            column += cell.col_span
        row_text = ' '.join(cell.text for _, cell in placed)
        unit_matches = UNIT.findall(row_text)
        if unit_matches:
            if len(set(unit_matches)) != 1:
                return ()
            unit = unit_matches[0]
        row_headers = {
            col: int(match[1]) for col, cell in placed
            if (match := COUNT.fullmatch(cell.text)) and cell.col_span == 1
        }
        if row_headers:
            if len(set(row_headers.values())) != len(row_headers):
                return ()
            headers = row_headers
            pending_label = ''
            continue
        if len(placed) == 1 and placed[0][1].col_span > 1:
            caption = row_text
            headers = {} if COUNT.search(row_text) else headers
            pending_label = ''
            continue
        if not headers or not unit:
            continue
        left = min(headers)
        labels = list(dict.fromkeys(cell.text for col, cell in sorted(grid.items()) if col < left and cell.text))
        label = ' '.join(labels)
        if pending_label and label.startswith(('(', '（')):
            label = f'{pending_label} {label}'
        numeric = [(col, cell) for col, cell in placed
                   if re.fullmatch(r'\d[\d,]*(?:\.\d+)?\s*(?:만원|천원|원)?', cell.text)]
        if not numeric:
            pending_label = label if label and all(not cell.text for col, cell in grid.items() if col >= left) else ''
            continue
        pending_label = ''
        if not label or not re.search(r'금액|지원액|지급액|급여|생계|재산|소득|기준', label):
            continue
        row_facts: list[HouseholdCell] = []
        for col, cell in numeric:
            targets = [headers[index] for index in range(col, col + cell.col_span) if index in headers]
            if len(targets) != 1:
                return ()
            row_facts.append(HouseholdCell(targets[0], cell.text, f'{caption} | {label}', unit,
                                           row_number, col + 1))
        if len({fact.household for fact in row_facts}) != len(row_facts):
            return ()
        facts.extend(row_facts)
    return tuple(facts)
