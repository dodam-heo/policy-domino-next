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
증거 기반 검토 초안 ── ai.py (Gemini: 공식자료 수집과 별도 실행)
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

# 공식 원천 수집·비교 (AI 호출 없이 실행)
python -m policy_domino run --limit 20

# 저장된 공식 변경 근거만 AI 검토 (실행당 요청 최대 2회)
python -m policy_domino ai --limit 2
python -m policy_domino ai-check
```

공식 법제처 공개 API OC 식별자는 기존 `dori`를 기본값으로 사용합니다. 본인의 발급값은 `LAW_OC` 환경변수로 덮어쓸 수 있습니다.

### 무료 Gemini AI 분석 (서버에서만)

Google Gemini `generateContent`의 **JSON 구조화 출력**을 사용합니다. 기본 모델은 무료 이용 구간이 있는 `gemini-3.1-flash-lite`입니다. 실제 무료 한도는 AI Studio 프로젝트별·모델별 설정에 따릅니다. Google 무료 티어의 데이터 사용 정책을 확인하고 비공개 내부문서는 전송하지 마세요. AI 입력은 공식 공개 변경 원문과 검증된 공공사업 근거로 제한합니다.

```bash
export GEMINI_API_KEY="Google AI Studio에서 발급한 API 키"
python -m policy_domino ai --limit 2
python -m policy_domino ai-check
```

- GitHub Actions의 **Settings → Secrets and variables → Actions**에 `GEMINI_API_KEY`만 등록하면 됩니다. 모델은 워크플로에 고정되어 있으므로 Variables 설정은 필요하지 않습니다.
- `run`은 공식자료 수집만 실행합니다. 별도 `ai` 단계가 **재시도를 포함해 API 요청 최대 2회**를 실행합니다. 일시적 Gemini 과부하(503)는 2초 간격으로 최대 한 차례만 재시도하며 이 재시도 역시 예산에 포함됩니다. 모두 실패해도 추가 호출을 반복하지 않습니다. 네트워크 타임아웃은 요청당 40초, Actions의 AI 분석 단계는 최대 4분입니다.
- 원문 발췌·기관명·사업 식별자·출처 SHA를 검증한 결과만 게시합니다. 동일 근거·동일 모델의 기존 검증 결과는 캐시로 재사용합니다.
- `ai_run`에는 시도·생성·재사용·오류 건수와 정형화된 실패 코드만 기록합니다. 인증키와 외부 모델의 오류 메시지/응답 원문은 기록하지 않습니다.
- `ai-check`는 `partial_generated`(일부 초안 생성)와 Gemini 500/503 등 일시적 장애를 **경고로 표시하며 전체 배포를 실패로 바꾸지 않습니다**. 키 누락, 권한 오류, 구조화 출력·근거 검증 실패는 여전히 실패 처리합니다. 검증된 AI 결과 및 실패 코드는 모두 보존됩니다. 분석 대상이 없으면 `no_eligible_changes`, 모두 캐시되었으면 `cached`를 표시합니다.
- GitHub Pages는 API 키를 받지 않으며 정적 페이지에서 직접 AI 모델을 호출하지 않습니다. GitHub Actions #78에서는 실제 Gemini 초안 1건 생성·검증 후 공식 데이터와 함께 배포됐고, 추가 요청 1건은 서버 과부하(503)로 실패했습니다. 기존 `OPENAI_API_KEY`와 `OPENAI_MODEL` 설정은 사용하지 않습니다.

## 프로젝트 설명서

- [아키텍처·데이터 계약·설계 선택](docs/ARCHITECTURE.md)
- [공식 공공사업 원문 검증·확인 범위](docs/PROGRAM_EVIDENCE.md)
- [품질 및 제출 기준](docs/ENGINEERING_STANDARD.md)

코드에서 공식 변경의 근거 수준과 AI 검토 초안의 추정 수준을 혼동하지 않는 것이 제품의 핵심 설계 원칙입니다. 테스트 데이터의 가상 정책·기관은 실데이터로 저장하거나 게시하지 않습니다.
