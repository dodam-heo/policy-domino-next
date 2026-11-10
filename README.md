# 정책도미노 NEXT

공식 정책 변경이 **어떤 조문을 어떻게 바꾸고**, 그 변경이 **어느 공공기관의 어떤 사업·업무에서 검토될 필요가 있는지**를 공식 자료와 AI 분석 초안을 이용해 추적하는 공개 소프트웨어입니다.

대상은 중앙행정기관·지방자치단체·교육청·공공기관 등 **공공부문**입니다. 민간조직은 기관별 영향분석 대상에 포함하지 않습니다. 정책, 기관, 사업, 예상 조치를 소스에 미리 등록하지 않습니다.

## 단일 실행 흐름

```text
공식 법령 API ── api.py / parser.py
       ↓
공식 변경 전·후 ── analysis.py
       ↓
관련 조문 인용 ── discovery.py + analysis.py
       ↓
공식 공공사업 원문 ── alioplus.py / programs.py
       ↓
증거 기반 검토 초안 ── ai.py (LLM: API 키가 있을 때만 실행)
       ↓
contracts.py (모든 출처·인용 검증) → pipeline.py (유일한 운영 경로)
       ↓
site/data.json → presentation.js (데이터 표시 모델) → app.js (화면 제어)
```

하나의 실제 운영 워크플로만 존재합니다: `.github/workflows/pipeline.yml`.

## 현재 구현한 기능

- 법령·행정규칙·자치법규의 최신 변경, 종전/현행 원문 비교, 조문 변경 부분 강조
- 공식 조문을 정확히 인용하는 관련 규정 연결
- 알리오플러스 공개 사업 본문 수집과 정확한 조문 인용 기반 사업 연결(범위 제한)
- **실제 LLM 분석**: 공식 신구 문구를 읽고 정책 변경 요약 및 기관·사업 검토 질문 초안을 생성. 모델 반환 문구가 공식 원문에서 확인되지 않거나 임의 기관·사업을 만들면 결과를 버림
- AI가 만든 검토 초안 / 공식 조문 인용 / 실제 업무 조치 필요성을 별개로 표시
- 최신순 정책목록, 신규·개정·폐지 검색, 모바일 목록→상세, 간결한 신구 비교, 기관명별 필터
- 수집 원천의 상태·오류 기록, 모델 입력 해시 검증, Python/JS 회귀 테스트

**구현하지 않았거나 실측이 부족한 기능:** 전국 모든 공공기관·지자체·교육청의 공고 및 사업자료 자동 수집, 공식 사업 기준의 실제 수정 의무 증명, 전국 단위 발견율 검증, 대용량 데이터 증분 저장·목록 상세 지연 조회. 현재 알리오플러스 원천은 첫 페이지 일부만 실제 검증했고 다음 페이지 조회는 미확인입니다. **미발견은 영향 없음이 아닙니다.**

## 실행 환경

Python 3.12+ 및 Node.js 20+; Python 외부 라이브러리 설치 없이 실행됩니다. 사용되는 공식 수집자료는 공개자료입니다.

```bash
# 기존 저장된 실제 공식 데이터로 공개 결과 다시 생성
python -m policy_domino render

# 테스트: 네트워크나 AI 요금 없이 실행
python -m unittest discover -s tests -p 'test_*.py' -v
node tests/test_site.cjs

# 공식 원천 수집 → 비교 → 연관 사업 확인 → AI 검토(인증키 있을 때만)
python -m policy_domino run --limit 20
```

공식 법제처 공개 API OC 식별자는 기존 `dori`를 기본값으로 사용합니다. 본인의 발급값은 `LAW_OC` 환경변수로 덮어쓸 수 있습니다.

### AI 분석 활성화 (서버에서만)

OpenAI Responses API의 **구조화된 JSON 출력**을 사용합니다. API 키와 모델 설정은 소스나 웹사이트에 기록하지 않습니다. ChatGPT 이용권과 API 사용 권한·과금은 별개입니다.

```bash
export OPENAI_API_KEY="발급받은 API 키"
export OPENAI_MODEL="gpt-4.1-mini" # 생략 가능
python -m policy_domino ai --limit 2
```

`ai` 명령은 저장된 공식 변경자료를 분석하고 `site/data.json`을 갱신합니다. `run` 명령도 `OPENAI_API_KEY`가 설정되어 있으면 수집 직후 제한된 건수의 AI 분석을 수행합니다. 키가 없으면 **`ai_status=not_configured`**로 남고, AI가 실행됐다고 표시하지 않습니다. 모델 API 호출 실패·증거 검증 실패 시에도 허위 초안을 배포하지 않습니다.

GitHub Actions 자동 운영에 연결하려면 저장소 **Settings → Secrets and variables → Actions → New repository secret**에서 `OPENAI_API_KEY`를 등록합니다. 선택적으로 Variables에 `OPENAI_MODEL`을 지정할 수 있습니다. GitHub Pages는 API 키를 받지 않으며, 정적 페이지에서 직접 LLM API를 호출하지 않습니다.

## 프로젝트 설명서

- [아키텍처·데이터 계약·설계 선택](docs/ARCHITECTURE.md)
- [공식 공공사업 원문 검증·확인 범위](docs/PROGRAM_EVIDENCE.md)
- [품질 및 제출 기준](docs/ENGINEERING_STANDARD.md)

코드에서 공식 변경의 근거 수준과 AI 검토 초안의 추정 수준을 혼동하지 않는 것이 제품의 핵심 설계 원칙입니다. 테스트 데이터의 가상 정책·기관은 실데이터로 저장하거나 게시하지 않습니다.
