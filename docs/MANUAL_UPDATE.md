# 매뉴얼 DB 업데이트 절차

새 매뉴얼 원본(PDF·HWPX)을 복지DB에 넣는 절차. 통합돌봄 대시보드 반영은 대시보드 저장소 `scripts/manuals/UPDATE.md`를 이어서 실행함.

## 1. 계획 확인

```powershell
.\.venv-openkb\Scripts\python.exe -X utf8 tools\manual_update.py --originals "C:\Users\Rumans\Desktop\26년 복지톡 8차 업데이트(원본)" --plan-only
```

- 원본마다 교체할 기존 문서를 파일명 유사도로 제안함. 1순위 점수 0.72 이상, 2순위와 0.08 이상 차이가 날 때만 자동으로 정함.
- 정하지 못한 원본이 있으면 종료 코드 3과 후보 3개를 출력함. 이때 매핑 파일을 만들어 `--map`으로 지정함.

```json
{
 "2026 새 매뉴얼.pdf": {"replaces": "[매뉴얼-분류] 2025 이전 매뉴얼.md"},
 "2026 신규 사업 안내.pdf": {"replaces": null, "category": "매뉴얼-분류"}
}
```

## 2. 실행

```powershell
.\.venv-openkb\Scripts\python.exe -X utf8 tools\manual_update.py --originals "<원본 폴더>" --push
```

| 단계 | 내용 |
| --- | --- |
| 변환 | kordoc 4.0.7(고정) JSON 출력. 설치본은 `%LOCALAPPDATA%\BokjiTalkManualUpdate\kordoc-4.0.7`에 한 번만 받음 |
| 교체 | `source-md`에서 이전 문서를 `git rm`하고 새 문서 저장. 이름은 원본명에서 `_`·`+`를 공백으로 바꾸고 분류 표기를 붙임 |
| 출처 기록 | `db-update-<날짜>.json`. 교체 전 문서는 `replaces`, 글자 층이 거의 없는 쪽은 `low_text_pages` |
| DB | `welfare_index.py build`와 같은 증분 색인 |
| 임베딩 | 포트 18081에 bge-m3 서버를 `-b 2048 -ub 2048`로 띄워 바뀐 구간만 계산하고 종료 |
| 사업 사전 | 전체 재생성. 출처 정렬은 이름순으로 고정돼 실행마다 같은 결과 |
| 기록 | README의 DB 수치, `DB_UPDATE_<날짜>.md` 자동 작성 |
| 검증 | 전체 pytest. 실패하면 커밋하지 않고 종료 |
| 커밋 | `--push`가 있으면 GitLab push(실패 시 60초 간격 3회) |

- 대시보드용 Kordoc JSON과 요약은 `%LOCALAPPDATA%\BokjiTalkManualUpdate\<날짜>\`(번들)에 남음.
- 같은 날짜로 두 번 실행할 수 없음. 다시 하려면 커밋하지 않은 변경을 git으로 취소하거나 `--date`를 바꿈.
- 골든 문항의 기대 문서는 출처 기록의 `replaces`를 따라 현재 문서로 찾으므로 고치지 않음.

## 3. 사람이 확인할 것

- 교체 대상이 맞는지(1단계 출력)
- `DB_UPDATE_<날짜>.md`의 "글자 층이 거의 없는 쪽"이 표지·간지인지, 그림으로만 된 본문인지
- 설치 파일 배포가 필요한지. 설치본 사용자는 새 설치 파일을 받아야 새 DB를 씀
