from decimal import Decimal

from welfare_table_facts import table_money_facts


def test_explicit_household_columns_with_empty_margin_spans() -> None:
    body = '''<table>
<tr><th colspan="4">2026년 기준 중위소득 (단위：원)</th></tr>
<tr><td rowspan="2"></td><td>구분</td><td>1인가구</td><td>2인가구</td></tr>
<tr><td>기준 중위소득</td><td>123</td><td>456</td></tr>
</table>'''
    facts = table_money_facts(body)
    assert [(f.household, f.amount_won) for f in facts] == [(1, Decimal(123)), (2, Decimal(456))]
    assert all(f.source_unit == '원' and '기준 중위소득' in f.indicator for f in facts)


def test_merged_value_across_two_households_is_rejected() -> None:
    body = '''<table>
<tr><th colspan="3">(단위：원)</th></tr>
<tr><td>구분</td><td>1인가구</td><td>2인가구</td></tr>
<tr><td>선정기준</td><td colspan="2">123</td></tr>
</table>'''
    assert table_money_facts(body) == ()


def test_unit_is_never_invented_for_html_numbers() -> None:
    body = '''<table><tr><td>구분</td><td>1인가구</td></tr>
<tr><td>선정기준</td><td>123</td></tr></table>'''
    assert table_money_facts(body) == ()


def test_split_criterion_label_keeps_the_benefit_identity() -> None:
    body = '''<table>
<tr><th colspan="3">2026년 수급자 선정기준 (단위：원)</th></tr>
<tr><td>구분</td><td>1인가구</td><td>2인가구</td></tr>
<tr><td>생계급여수급자</td><td></td><td></td></tr>
<tr><td>(기준중위소득 32%)</td><td>123</td><td>456</td></tr>
</table>'''
    facts = table_money_facts(body)
    assert len(facts) == 2
    assert all('생계급여' in f.indicator and '32%' in f.indicator for f in facts)
