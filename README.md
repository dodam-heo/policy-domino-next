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

기존 프로젝트에서 사용하던 공개 법제처 공동활용 OC 식별자 `dori`를 **소스코드의 기본값으로 그대로 적용**했습니다. `LAW_OC`가 없어도 공식 API 수집을 시도합니다. 다른 인증값으로 변경하려는 경우에만 `LAW_OC` 환경변수(또는 GitHub Secret/Variable)를 설정하세요. 이 공개 OC 식별자 이외에 개인 비밀키를 코드에 저장하지 않습니다. 초기 데이터는 가짜 정책을 삽입하지 않은 **빈 공식 목록**이며, 실제 수집 전까지 실데이터가 아닙니다.

## GitHub 신규 저장소 설정

1. **[새 저장소 GitHub Pages 설정](https://github.com/dodam-heo/policy-domino-next/settings/pages)** → Build and deployment → Source: **GitHub Actions** 지정.
2. [Actions](https://github.com/dodam-heo/policy-domino-next/actions/workflows/pipeline.yml)에서 최초 실행 또는 다음 정기 실행 확인.
3. 실제 수집·추출·비교 건수와 공식 근거를 확인. `LAW_OC` Secret은 **필수 아님**.

이전 프로젝트는 참고자료로만 보존하고 새 저장소에서 운영하지 않습니다.

## 코드 품질과 공식 근거 계약

화면은 `site/index.html`(구조), `site/styles.css`(표현), `site/app.js`(상태·화면 제어)로 나누었고, `policy_domino/contracts.py`가 생성 직전 및 배포 직전 공식 원문·조문 비교·기관 영향의 검증 수준을 공통 검사합니다. 데이터 수집과 페이지 제어가 특정 기관이나 분야별로 분기하지 않도록 모듈 경계를 유지합니다.

**[제출을 위한 엔지니어링 기준과 미완성 과제](docs/ENGINEERING_STANDARD.md)** 를 별도 문서로 관리합니다. 특정 조직 개편이나 급여 변경을 기준으로 코드를 분기하지 않고, 여러 종류의 정책 변경이 동일한 검증 파이프라인을 거치는지 평가합니다.
