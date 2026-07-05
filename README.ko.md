# PaperFlow (한국어)

**Zotero ↔ Obsidian 사이를 자동으로 잇는 로컬 논문 파이프라인 오케스트레이터.**

새 논문이 Zotero에 들어오면: Obsidian 노트 자동 생성(Papers_Zotero_v3 호환) → PDF 확보(OA 우선, 예의 바른 속도제한) → AI 분석 큐 적재 → 분석 완료 자동 감지 → vault index/log 갱신. 분석 자체는 내 에이전트 워크플로우(Claude 배치)가 담당하고, PaperFlow는 큐 공급과 완료 감지를 맡는다.

전부 내 컴퓨터 안에서 동작. 클라우드 계정·API키 불필요, 런타임 의존성 0 (Python ≥ 3.9 표준 라이브러리만).

## 일상 사용 흐름

1. 평소처럼 논문을 Zotero에 추가 (브라우저 Connector 등)
2. 데몬이 2분 내 감지 → 노트·PDF·큐 자동 처리
3. 분석하고 싶을 때: `paperflow queue`로 목록 확인 → Cowork에서 "미분석 논문 배치 분석해줘" (기존 `prompts/analyze_paper.md` 계약 그대로)
4. 분석노트가 생기면 PaperFlow가 자동 감지해 큐에서 제거, index.md 카운트 갱신

## 설치

```bash
cd ~/Documents/PaperFlow
python3 -m paperflow.cli init          # ~/.paperflow/config.toml 생성
# config.toml 편집: [vault] dir, [pdf] unpaywall_email
python3 -m paperflow.cli doctor        # 환경 점검
python3 -m paperflow.cli run-once --dry-run   # 미리보기
python3 -m paperflow.cli run-once             # 실제 1회 실행
python3 -m paperflow.cli install-daemon       # launchd 등록 파일 생성(자동 로드 안 함)
launchctl load ~/Library/LaunchAgents/com.paperflow.daemon.plist   # 상시 가동 시작
```

## 안전 보장

- **Zotero에는 읽기 전용.** zotero.sqlite는 임시 복사본으로만 읽고, DB·storage/에 절대 쓰지 않음. 받은 PDF는 `~/.paperflow/pdfs/`에 저장.
- **Vault 보호.** 기존 노트는 절대 덮어쓰지 않음(`## My Synthesis` 완전 보존). index.md는 진척 카운터만 정규식으로 정밀 수정, log.md는 append만, 삭제 코드 경로 자체가 없음.
- **다운로드 예절.** OA 우선(arXiv·Unpaywall), 순차+지연, 일일 한도(기본 20). 대량 긁기로 학교 IP가 차단당하는 사고 방지를 위해 일부러 느리게 설계.
- **감사 가능.** 모든 자동 행동이 trace에 기록 (`paperflow trace`).

## 명령어

`init` 설정 생성 · `doctor` 점검 · `run-once [--dry-run]` 1회 실행 · `daemon` 상시 폴링 · `install-daemon` launchd 등록 · `queue [--json]` 미분석 목록 · `status` 상태 요약 · `trace` 감사 로그.

## 로드맵

- **M2**: 로컬 translation-server 통합(DOI 하나로 Zotero 추가) + 웹 대시보드(검색→체크→추가)
- **M3**: UIC 프록시 폴백(라이선스 논문 자동 확보)
- **M4**: 인용그래프 · 관련논문 추천(로컬 임베딩) · arXiv 키워드 알림 · synthesis 자동 제안
- **M5**: Polaris 연동 + 오픈소스 공개 정리
