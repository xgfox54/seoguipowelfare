#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# dependencies = []
# ///
# How to run: .venv-openkb\Scripts\python.exe tools\build_program_cards.py [--check]
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CARD_DIR = ROOT / 'knowledge' / 'program_cards'
SOURCE_DIR = ROOT / 'source-md'
DATABASE = ROOT / 'wiki' / 'kb-v120' / 'welfare.db'
OUTPUT = ROOT / 'resources' / 'program_cards.json'
FIELDS = ('대상', '선정기준', '지원내용', '금액', '지원기간', '신청방법', '제외조건')
COMPACT_DROP = re.compile(r'<[^>]+>|[\s#*|`/]+')
NUMBER = re.compile(r'\d[\d,]*(?:\.\d+)?')


class CardError(Exception):
    pass


def compact(text: str) -> str:
    return COMPACT_DROP.sub('', text.replace('\\', ''))


def numbers(text: str) -> set[str]:
    return {match.replace(',', '') for match in NUMBER.findall(text)}


def database_hashes() -> dict[str, str]:
    with sqlite3.connect(DATABASE) as connection:
        return dict(connection.execute('SELECT source_name, sha256 FROM documents'))


def verify_card(card: dict, hashes: dict[str, str], errors: list[str]) -> dict:
    name = card['source_name']
    path = SOURCE_DIR / name
    if not path.is_file():
        raise CardError(f'{card["id"]}: source missing {name}')
    raw = path.read_bytes()
    digest = hashlib.sha256(raw).hexdigest()
    if hashes.get(name) != digest:
        raise CardError(f'{card["id"]}: source hash differs from database for {name}')
    lines = raw.decode('utf-8').splitlines()
    if set(card['fields']) - set(FIELDS):
        raise CardError(f'{card["id"]}: unknown field {sorted(set(card["fields"]) - set(FIELDS))}')
    for field, facts in card['fields'].items():
        for index, fact in enumerate(facts):
            start, end = fact['lines']
            if not 1 <= start <= end <= len(lines):
                errors.append(f'{card["id"]} {field}[{index}]: bad line range {start}-{end}')
                continue
            window = compact(' '.join(lines[start - 1:end]))
            quotes = fact['quotes']
            for quote in quotes:
                if compact(quote) not in window:
                    errors.append(f'{card["id"]} {field}[{index}]: quote not in lines {start}-{end}: {quote[:60]}')
            quoted = set().union(*(numbers(quote) for quote in quotes)) | {card['year']}
            window_digits = window.replace(',', '')
            missing = {n for n in numbers(fact['text']) - quoted if n not in window_digits}
            if missing:
                errors.append(f'{card["id"]} {field}[{index}]: numbers not in quotes {sorted(missing)}')
            fact['evidence'] = '\n'.join(lines[start - 1:end])
    return {**card, 'source_sha256': digest}


def build() -> list[dict]:
    hashes = database_hashes()
    cards = [json.loads(path.read_text(encoding='utf-8')) for path in sorted(CARD_DIR.glob('*.json'))]
    ids = [card['id'] for card in cards]
    if len(ids) != len(set(ids)):
        raise CardError('duplicate card id')
    errors: list[str] = []
    verified = [verify_card(card, hashes, errors) for card in cards]
    if errors:
        raise CardError('\n'.join(errors))
    return verified


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--check', action='store_true', help='verify only; do not write the output')
    args = parser.parse_args()
    sys.stdout.reconfigure(encoding='utf-8')
    try:
        cards = build()
    except CardError as error:
        print(f'FAILED: {error}')
        return 1
    payload = json.dumps({'version': 1, 'cards': cards}, ensure_ascii=False, indent=1) + '\n'
    if args.check:
        current = OUTPUT.read_text(encoding='utf-8') if OUTPUT.is_file() else ''
        if current != payload:
            print('FAILED: resources/program_cards.json is stale')
            return 1
    else:
        OUTPUT.write_text(payload, encoding='utf-8')
    print(f'OK {len(cards)} cards, {sum(len(f) for c in cards for f in c["fields"].values())} facts')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
