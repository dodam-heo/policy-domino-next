# 정책도미노 NEXT

**공식 규범의 제·개정 → 정책 변경 사건 → 영향받는 공공기관의 업무·사업 → 근거가 있는 변경 검토사항**을 추적하는 공공부문 정책 영향 분석 서비스.

중앙행정기관·지방자치단체·교육청·공공기관 등 **공공조직만** 영향 분석 대상으로 다룬다. 특정 기관명·사업명·법령명이나 정책 예시를 분석 로직의 정답으로 하드코딩하지 않는다. 단순한 법령 검색 서비스나 AI 요약 서비스가 아니다.

## 구현 아키텍처

```text
official legal API (law, admrul, ordin)
   ↓ api.py, parser.py            [원천 목록·공포 식별자·공식 버전]
state.documents, state.versions
   ↓ analysis.py                  [실제 신구 차이, 원문 SHA]
state.findings
   ↓ discovery.py + programs.py   [정확한 법령 인용, 실제 공개 사업 인용]
   ↓ events.py                    [공포번호·일자에 따른 정책 사건 구성]
     ├─ change event             [공식 변경 사건 1건, 구성 법령 N건]
     ├─ source changes           [실제 변경 조문·변경 전후·원문]
     ├─ institutional reviews    [직접 규율기관 / 명시 수행주체 / 검증 사업 인용]
     └─ related rules            [별도 근거 등급의 법령 인용 관계]
   ↓ ai.py (optional Gemini)      [확인된 기관·조문·사업에 대한 근거 제한 AI 보조검토]
   ↓ contracts.py                [사건 병합·기관 연결·인용·AI 요약 모두 재검증]
   ↓ pipeline.render()
site/data.json → presentation.js → app.js → index.html
```

**문서(document)**는 원천 수집·검증 기록이고 **정책 사건(event)**은 사용자에게 보여주는 핵심 분석 단위다. 동일한 공포번호·공포일·법령 종류로 공식 동일 사건임이 확인될 때만 여러 법령을 병합한다. 같은 제목이나 주제라는 이유만으로 병합하지 않는다. 신규·개정·폐지 사실과 신구 비교가 확인되지 않은 색인 항목은 변경 사건으로 게시하지 않는다.

## 사용자 화면

첫 목록은 확인된 **정책 변경 사건 최신순**이다. 제정·개정·폐지·기관 영향·급여/지원기준으로 볼 수 있으며, '신구 확인' 같은 내부 처리 단계는 사용자 필터로 표시하지 않는다.

사건 상세:

1. **이번 변경의 핵심**: 묶인 공식 법령과 실제 변경 조문의 핵심 차이
2. **기관별 변경 검토사항**: 공공기관명 아래 업무·사업·변경 대상 조문·검토 사항을 묶어 표시
3. **공식 신구 대조·근거**: 자세한 전후 원문, 개정 법령 목록 및 관계 규정은 접어서 제공
4. **AI 보조검토**: 원문 검증을 통과한 추가 분석만 해당 업무 카드 및 접힌 상세에 제공

직접 규율기관, 공식 변경 조문에 명시된 수행주체, 공식 사업 문서의 정확한 조문 인용은 **서로 다른 증거 등급**으로 구분한다. 법령 발령기관·주제 유사성만으로 영향기관을 임의 생성하지 않는다. **기관별 검토 대상**과 **실제 후속 조치 완료/미완료**는 전혀 다른 상태이며 현재 후자는 확인되지 않는다.

## 운영·테스트

Python 3.12+, Node.js. 외부 Python 패키지 설치 없이 실행 가능. 단일 GitHub Actions 워크플로 `.github/workflows/pipeline.yml`.

```bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m policy_domino render
node tests/test_site.cjs
python -m policy_domino.contracts site/data.json

# 공식 수집과 비교 (AI 호출 없이)
python -m policy_domino run --limit 20

# 현재 검증된 조문·기관 근거로 Gemini 보조 검토
GEMINI_API_KEY="발급된 키" python -m policy_domino ai --limit 24
python -m policy_domino ai-check
```

GitHub Actions의 `GEMINI_API_KEY` Secret으로만 API에 접근하며 프런트엔드에 키를 제공하지 않는다. 기본 모델은 `gemini-3.1-flash-lite`, 기본 요청 예산은 **재시도 포함 실행당 24회**다. 429는 중단, 503 등 과부하는 제한된 재시도만 수행하고 처리된 초안은 해시 기준으로 재사용한다. 실제 무료 한도는 AI Studio 프로젝트/모델의 제한을 따른다.

## 현재 제한

- 법제처의 공식 원천과 조문 원문을 계속 수집하지만, **수집 색인 전체가 신구 대조·기관 영향 분석 완료된 것은 아니다**.
- 알리오플러스 기관별 사업은 현재 **첫 페이지 일부 상세자료만** 수집하며 전국 기관의 실제 사업·내부 운영 규정을 포괄하지 않는다. 정확한 조문 인용이 없더라도 실제 영향을 받는 업무가 있을 수 있다.
- 관련 법령 인용만으로 실제 사업 수정 의무를 확정하지 않으며, 공공기관의 조치 완료 여부를 관측하는 엔진은 미구현이다.
- 공개 데이터는 아직 단일 JSON이므로 지연 조회·증분 DB 저장은 개발 과제다.
- 테스트에 나오는 정책·기관은 합성 예제이며, 구 프로젝트의 표시 결과는 현재 분석 데이터로 복사하거나 가져오지 않는다.

자세한 설계는 [아키텍처](docs/ARCHITECTURE.md), [기관·사업 근거 계약](docs/PROGRAM_EVIDENCE.md), [품질 기준](docs/ENGINEERING_STANDARD.md)을 참고한다.
