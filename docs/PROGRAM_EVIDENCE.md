# 공식 공공사업 연결 엔진 — 범위·증거 계약

## 목적

정책 변경 → 직접 인용된 하위 규정 → 공공기관 실제 사업 안내의 명시적 인용을 추적한다. 수집된 기관명, 업무 주체, 단순 주제 유사도만으로 기관에 수정 의무가 있다고 표시하지 않는다.

## 코드 경계

- `policy_domino/alioplus.py`: ALIOPLUS 공공사업 *공식 페이지*를 소량·제한적으로 조회하는 외부 원천 어댑터. 원문 구조가 예상과 다르면 실패로 기록하고 조용히 가짜 사업 레코드를 생산하지 않는다.
- `policy_domino/programs.py`: 공식 페이지의 사업명·기관명·본문·원문 해시를 보존하고, 변경 조문과 정확한 인용이 있는 경우에만 사업 연관 관계를 만든다. 같은 조문이 중간 규정에서 인용되고 사업 안내가 해당 중간 규정의 정확한 조문을 인용하면 2단계 경로도 연결한다.
- `policy_domino/pipeline.py`: 성공·실패를 개별 감사자료로 보관. 법령 수집 실패나 사업 페이지 파싱 실패가 기존 결과 삭제로 이어지지 않는다.
- `policy_domino/contracts.py`: 생성된 연결 결과의 변경 사건·조문·공식 사업 URL·직접 인용 또는 중간 규정 경로의 증거를 공개 전 검사한다.

## 상태/데이터 계약

내부 상태 `official_programs`: 공식 사업 URL로 중복 제거된 기관명, 사업명, 안내 원문과 SHA-256. `program_source_audit`: 페이지 조회 횟수, 오류, 미수집 상태.

공개 `program_dependencies[]`:
- `agency`, `program`, `program_url`, `program_body_sha256`
- `source_event_id`, `changed_article`, `path`(direct/via_regulation)
- `referenced_title`, `referenced_article`, `citation_quote`
- `operational_program_verified=true`, `required_action_verified=false`
- `review`: 의무 확정이 아닌 적용 기준 검토 문구
- 사업 안내에 구판의 **하나로 특정 가능한 금액**이 그대로 남아 있으면 `old_value/new_value`를 기록하되, 개정 의무나 기관의 반영 완료 여부는 확정하지 않는다.

모든 연결은 ALIOPLUS 사업 본문에 **정확한 조문 인용**이 확인된 경우만 생성된다. 단순 법령명, 발령기관, 명사 빈도, 문서 검색 순위만으로 연결하지 않는다.

## 본 단계의 제한 및 남은 개발 과제

- ALIOPLUS는 중앙 공공기관의 사업 목록 원천 중 하나로, **지방공기업(SH 등)과 중앙행정기관·지자체·교육청을 포함한 전국 공공부문 전체를 대표하지 않는다.** 소스 어댑터 추가와 공식 기관 디렉터리/사업 공고의 인용·구판 판별이 필수다.
- 현 어댑터는 공개 사업 목록의 한 페이지를 제한된 건수로 조회하며, 실제 페이지 구조와 응답 안정성에 따른 실서비스 검증 전이다. `complete=false`를 유지한다. 장기 수집에서는 API 정식 인증 연계 또는 검증된 페이지네이션이 필요하다.
- 정확한 조문 인용이 없는 사업도 실제 영향을 받을 수 있다. **미발견은 영향 없음이 아니다.** 주제 후보 검색 → 공식 원문 재조회 → 법률 적용 문구 검증의 순서로 탐색 범위를 확대해야 한다.
- 실제 문서 개정 필요성을 강하게 결론내리려면 사업 안내의 **동일 기준 위치**, 적용 시점, 기관 업무 기준의 전후 또는 공식 변경 공고를 별도로 확인해야 한다. 이 엔진은 그러한 의무를 만들어내지 않는다.
- 현재 화면은 신규 `program_dependencies`를 표시하지 않는다. 이를 업무 조치로 혼동하지 않는 UI를 별도로 설계하고 웹 회귀 테스트를 통과해야 한다.
- 수집 데이터의 증분 DB 저장과 목록·상세 지연 조회는 별도의 작업이다. 장기 보관 상태와 공개 JSON을 구분한다.

## 재현 및 검증

~~~bash
python -m unittest discover -s tests -p 'test_*.py' -v
python -m policy_domino render
python -m policy_domino.contracts site/data.json
~~~

`tests/test_programs.py`는 직접 인용, 정확한 중간 인용, 잘못된 조문, 법령명만 언급한 경우, 위장 도메인, 중복 사업, 실제 검토사항과 조치 의무의 분리를 검증한다. 테스트 자료의 정책과 기관은 모두 가상이며 제품 데이터에 저장하지 않는다.
