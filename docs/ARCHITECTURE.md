# 정책도미노 NEXT — 시스템 전체 설계서

기준: 2026-11-10 / 설계 버전 1.0 / 범위: 대한민국 공공부문

## 1. 목표와 예외 없는 원칙

**정책 변경 자동 발견 → 실제 신구 본문 비교 → 파급되는 규정·기관·사업 자동 발견 → 근거 있는 기관별 검토사항 → 결과 제공 및 갱신.**

- 대상으로 삼는 조직: 중앙행정기관, 지자체, 교육청, 공공기관 등 공공부문. 민간조직은 기관별 업무 영향분석 대상에 포함하지 않는다.
- 법령·고시·자치법규 외 공공사업 운영지침·공고도 궁극적인 증거 원천에 포함한다.
- 특정 정책명, 기관명, 사업명, 기준금액, 공식 페이지, 기대 조치 문구는 코드나 운영 JSON에 사전 등록하지 않는다.
- 기관의 내부 시스템 변경 여부나 실제 조치 완료는 별도 증거 없이는 절대 확정하지 않는다.
- 수집된 변경이 미분석인 것은 영향이 없는 것이 아니다. 대기·부분·실패 상태를 구분한다.
- 예시 테스트 자료는 가상값만 사용하고 제품 데이터에 삽입하지 않는다.

## 2. 한 개의 운영 경로

~~~text
국가법령정보 API (law, admrul, ordin)
   ↓
policy_domino/api.py              공식 ID·버전·날짜창·페이지 감사
   ↓
policy_domino/parser.py           공식 XML 조문·별표·부칙의 실본문 추출
   ↓
policy_domino/analysis.py         종전·현행 조문 비교 및 동적 기준 식별
   ↓
policy_domino/analysis.py         실제 변경 조문을 직접 인용하는 규정 검증
   ↓
기관 공식 사업자료 발견 및 적용 관계 재검증 [현재 미구현]
   ↓
policy_domino/pipeline.py         유일한 운영 진입점, 상태 관리, 결과 계약
   ↓
data/state.json → site/data.json → site/index.html
   ↓
.github/workflows/pipeline.yml    단 하나의 테스트·수집·배포 워크플로
~~~

이 저장소에는 옛 V2/V3/V4, watch.py, impact_scanner.py를 복사하지 않았다. 예전 저장소의 결과 JSON도 실행에 사용하지 않는다. 원천 클라이언트, 검증 상태, 데이터 계약 및 배포는 하나로 합쳤다.

## 3. 수집 범위와 원천

| 원천 | API / 대상 | 원문 방식 | 상태 |
|---|---|---|---|
| 법률·시행령·시행규칙 | lawSearch.do target=law, 법령연혁 eflaw | lawService.do target=law, MST | 구현 / 실 API 검증 필요 |
| 고시·훈령·예규 등 행정규칙 | lawSearch.do target=admrul, 연혁 모드 | lawService.do target=admrul, ID | 구현 / 응답 형식 추가 검증 필요 |
| 지자체 조례·규칙 | lawSearch.do target=ordin, 연혁 모드 | lawService.do target=ordin, MST | 구현 / 지자체별 실측 필요 |
| 기관별 공고·사업 운영지침 | 기관 공식 사이트에서 동적 발견 | 게시일·사업명·기준·공고 원문 재조회 | 미구현 |
| 법제처 외 정부·공공 API | 출처와 제공 범위 먼저 확인 | 출처별 정규화 + 증거 해시 | 미구현 |

모든 목록은 날짜창 단위 totalCnt, 실제 페이지·레코드 수, 실패·불완전 여부를 저장한다. 최근 7일과 과거 역추적 7일을 병행한다. 기간이 너무 크면 반으로 분할한다. 네트워크 오류나 필터 불일치는 “변경 0건”으로 처리하지 않는다. 총 처리 한도는 **한 번 실행하는 처리량**이지 전체 발견율이 아니다.

## 4. 버전 비교의 안전성

- 이벤트 ID: SHA-256(source | 공식 stable ID | 버전 일련번호)의 앞 24자리.
- 종전 버전: 동일 official stable ID의 현재 이전 공포일·버전. 공식 연혁 확인을 우선한다.
- 연도별 고시는 특정 정책을 사전 등록하지 않고 제목에 존재하는 연도만 전년으로 변환, 실제 공식 구판을 다시 조회한 경우에만 비교한다.
- 이전 원문이 없거나 별표 내용이 첨부 링크뿐이면 “비교 불가”다.
- 긴 조문은 완전한 조문끼리만 비교한다. 일부만 비교했다면 partial_compared이고 나머지는 excluded이다.
- 변경 내역은 조문, 원문 before/after, 실제 차이 발췌, 추출 금액, 이전/현재 본문 SHA-256, 출처 URL을 보존한다.
- 직접 인용 관계는 문서명뿐 아니라 **정확한 변경 조문 번호**가 일치해야 한다.

## 5. 기관별 영향의 증거 계층

| 계층 | 판정 기준 | 상태 |
|---|---|---|
| 0. 공식 목록 | 공포/발령 정보 및 원천 ID 수집 | queued |
| 1. 변경 내용 | 공식 이전·현재 원문 차이 대조 | compared / partial_compared |
| 2. 관련 규정 | 변경된 조문을 다른 공식 문서가 정확히 인용 | verified_exact_article_citation |
| 3. 기관·사업 | 공공기관의 **실제 사업 자료**와 개정 기준 적용 관계를 원문에서 교차 검증 | verified_program_dependency (미구현) |
| 4. 구체적 조치 | 기관·사업 기준표/신청서/기한 등에 전후 내용이 어떻게 영향을 주는지 명시 | verified_action_to_review (미구현) |
| 5. 조치 완료 | 기관의 명시적 시행 결과나 수정 완료 증빙 | verified_completion (미구현) |

단순한 발행 기관·제목 인용·웹 검색 결과는 계층 3 이상의 근거가 아니다. 실제 사업과 기관 명칭은 기관 공식 자료에서 발견해야 한다. 프로젝트가 이전에 실패한 핵심 이유는 이 단계들을 하나의 ‘영향기관’으로 섞은 데 있다.

### 3·4계층의 목표 구현 방법

1. 정책 원문의 변경된 금액·자격·대상·절차·기한·사업 적용 범위를 자동 추출한다.
2. 실제 변경 조문을 인용하는 하위 규정과 공공기관 공고·사업 지침 후보를 분야 제한 없이 탐색한다.
3. 후보 원문을 다시 내려받고 발행기관, 사업명, 해당 기준 적용 문장, 구판/현판 시점을 기록한다.
4. “정책 조문 → 하위 기준 → 기관 업무 → 사업” 각각의 연결마다 URL, 발행일, 원문 일부, 적용 이유를 요구한다.
5. 모순·인용 불일치·개정 시점 불일치·민간기관 오인·과거 금액의 동음이의를 걸러낸다.
6. 근거 부족 시 확정된 업무 조치가 아니라 검토 후보로만 제공한다.

## 6. 하나의 데이터 계약

site/data.json: schema = policy-domino-next-v1

- documents[]: id, source, stable_id, serial, title, published_at, effective_date, revision, ministry, kind, url, analysis.
- analysis.status: queued / compared / partial_compared / no_text_change / enactment / repeal / history_unavailable / baseline_unavailable / body_unavailable / partial_unresolved / source_error.
- analysis.changes[]: article, before, after, actual_edits, category, old_values, new_values, source_url, evidence.
- analysis.review_candidates[]: 기관이 미배정된 실제 변경 조문 검토 후보.
- analysis.direct_actor_reviews[]: 변경 전후 공식 조문에 모두 명시된 수행주체에 한정한 직접 조문 검토. 실제 별도 기관 사업·조치 의무 확정은 아님.
- relationships[]: source_event_id, referencing_document_id, referencing_article, changed_article, official_url, reference_quote, publishing_agency, explicit_actors, relationship, operational_program_verified=false, required_action_verified=false.
- coverage[]: source, 날짜범위, edition, reported, collected, pages, complete, error.
- quality: 원천별 indexed, verified_changes, waiting, unavailable_bodies, unavailable_history.
- configuration: running / not_run_or_credential_missing.

data/state.json: documents, versions, findings, coverage, attempts, cursor_days, errors, generated_at. 구판을 비교 목적으로 다운로드한 경우 reference_only로만 저장하고 최신 변경 목록에 중복 노출하지 않는다.

## 7. 기능별 완료 기준

| 기능 | 완료 기준 | 현 단계 |
|---|---|---|
| 단일 운영 구조 | 기존 코드 의존 0, 운영 워크플로 정확히 하나 | 구현 |
| 공공 원천 3종 수집 | 세 유형별 공식 응답 수·수집 수 실측, 실패와 빈 결과 분리 | 합성 테스트 완료, 실측 필요 |
| 본문 추출 | 번호 조문·평문·별표·부칙·자치법규·첨부파일만 있는 응답 테스트 | 기본 구현 |
| 신구 비교 | 공식 이전본과 현판의 조문·금액 차이, 원문 해시 증거 | 기본 구현 |
| 대기열·재검증 | 문서 누락 방지, 실패·부분 상태, 인증/네트워크 실패 감지 | 기본 구현 |
| 인과 그래프 | 정확히 바뀐 조문 번호를 인용한 문서만 연결 | 기본 구현 |
| 기관·사업 자동 탐색 | 기존에 등록되지 않은 기관·사업을 여러 분야에서 자동 발견하여 독립 검증 | **미구현** |
| 기관별 조치 | 실제 사업 기준 변경 위치 및 행동을 구체적으로 제시하고 허위 양성 검증 | **미구현** |
| 전국 공공기관 확대 | 공고·운영 기준을 포함하여 원천별 발견율·재현율 검증 | **미구현** |
| 모바일·데스크톱 UI | 변경 전후 바로 아래 기관별 검토, 확인·미확인 구분 | 기본 구현 |
| 자동 배포 | 새 저장소 자체 Secret 및 Pages 설정 후 실제 공개 성공 | 설정·실행 확인 필요 |

**최종 완성 조건:** 임의로 정한 기관이나 정책명 없이 신규 공식 변경 사건 20건 이상을 독립 자료로 재현하고, 실제 기관·사업 적용 문서 및 조치 위치까지 확인해야 한다. 합성 테스트만 통과했다고 “전국 공공부문 연쇄 영향 분석 완성”이라고 표시하지 않는다.

## 8. 보안과 운영

- 기존 공개 프로젝트에서 검증한 법제처 공동활용 OC 식별자 `dori`를 소스의 기본값으로 사용한다. `LAW_OC` Secret/Variable은 선택적 덮어쓰기 수단이다. 비공개 인증키·계정 비밀번호는 코드에 저장하지 않는다.
- Pages Source는 GitHub Actions를 사용한다.
- `render`만 수행하고 공식 원천 조회가 없으면 data.json configuration은 미실행 상태를 유지한다. `run`은 `LAW_OC`를 지정하지 않아도 기존 공개 OC로 실제 원천 접근을 시도하고, 실패하면 coverage.error로 기록한다.
- 기존 policy-domino의 코드·사이트·설정·API 시크릿은 삭제하거나 변경하지 않는다.

공식 문서:
https://open.law.go.kr/LSO/openApi/guideResult.do
https://open.law.go.kr/LSO/openApi/guideResult.do?htmlName=lsNwInfoGuide
