# 정책도미노 NEXT

공식 정책 변경 → **실제 변경 전후** → **관련 규정** → **공공기관·사업 적용 근거** → **기관별 검토사항**을 자동 추적하는 독립 재구축 프로젝트.

이 저장소는 기존 policy-domino 저장소와 코드·데이터·배포가 분리되어 있습니다. V2/V3/V4/watch.py/impact_scanner.py를 실행하지 않습니다. 특정 기관·사업·금액·조치 사항을 미리 심지 않습니다. 민간조직은 업무 영향 분석 대상에서 제외합니다.

## 단일 운영 경로

~~~text
policy_domino.api → policy_domino.parser → policy_domino.analysis
                                       ↓
                             policy_domino.pipeline
                             ↓                  ↓
                        data/state.json     site/data.json
                                                ↓
                                          site/index.html
~~~

단 하나의 운영 워크플로: .github/workflows/pipeline.yml

전체 목적, 데이터 구조, 원천 범위, 영향 알고리즘 및 기능별 완료 기준: [시스템 설계서](docs/ARCHITECTURE.md).

## 현재 구현 수준

구현: 법령·행정규칙·자치법규 공식 API 클라이언트, 조문·별표·부칙 추출, 전후 비교, 변화 조항의 정확한 인용 확인, 재시도·대기열, 단일 데이터 계약, 초기 웹 화면, 독립 단위 테스트 및 자동화.

**아직 구현하지 못한 핵심:** 공공기관의 실제 사업·공고 자동 발굴, 법령 변경과 사업 기준의 적용 관계 검증, 확정된 기관별 업무 조치. 또한 실 API의 모든 응답 형태와 전국 커버리지는 검증되지 않았습니다. 이를 완성된 서비스라고 표시하지 않습니다.

## 사용

Python 3.12 이상, 표준 라이브러리만 사용합니다.

~~~bash
python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_site.cjs
python -m policy_domino render
~~~

공식 변경 수집:

~~~bash
export LAW_OC="발급받은 법제처 인증값"
python -m policy_domino run --limit 30
~~~

LAW_OC가 없으면 실제 API 수집은 실행하지 않으며 미실행 상태로 표시합니다. 초기 데이터는 예시 정책을 꾸며 넣지 않은 **빈 공식 목록**입니다.

## GitHub 신규 저장소 설정

1. Settings → Secrets and variables → Actions에서 새 Repository Secret **LAW_OC** 등록.
2. Settings → Pages → Build and deployment → Source: **GitHub Actions** 지정.
3. Actions → Policy Domino NEXT - Single Production Pipeline → Run workflow 실행.
4. 실제 원천 수집 결과와 검증·부분·실패 상태를 살핀 후 Pages 공개 여부 확인.

이전 프로젝트는 참고자료로만 보존하고 새 저장소에서 운영하지 않습니다.
