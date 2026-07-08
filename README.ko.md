# ZotVault (한국어)

**Zotero ↔ Obsidian 사이를 자동으로 잇는 로컬 논문 파이프라인 오케스트레이터.**

새 논문이 Zotero에 들어오면: Obsidian 노트 자동 생성 → PDF 확보(OA 우선, 예의 바른 속도제한, 옵션으로 학교 프록시 폴백) → AI 분석 큐 적재 → 분석 완료 자동 감지 → index/log 갱신. 여기에 DOI 원샷 추가, 논문 검색, 로컬 대시보드, arXiv 키워드 알림, 인용 그래프, 임베딩 기반 관련논문 추천, synthesis 클러스터 제안까지.

전부 내 컴퓨터 안에서. 코어 루프에 API키 불필요, 런타임 의존성 0 (Python ≥ 3.9 표준 라이브러리만).

## 일상 사용 흐름

1. **수집** — 3가지 아무거나:
   - 평소처럼 브라우저 Zotero Connector
   - `zotvault add 10.1103/PhysRevB.1.1` 또는 대시보드에서 검색→체크→추가
   - arXiv 알림 인박스에서 승인 클릭
2. 데몬이 2분 내 감지 → 노트·PDF·큐 자동 처리 (PDF 형광펜·그림 주석은 노트의 마커 블록에 edit-safe 동기화, 색상 그룹명은 내 기준으로 변경 가능)
3. 분석: `zotvault queue` 확인 → Cowork에서 "미분석 배치 분석" (기존 계약 그대로) → 완료 자동 감지
4. 매일: 알림 다이제스트 + 인용그래프/관련추천/synthesis 제안 노트 자동 갱신

## 대시보드

```bash
zotvault web   # → http://127.0.0.1:8377 (localhost 전용)
```

검색→추가, 분석 큐, arXiv 인박스, synthesis 제안, 감사 로그 한 화면.

## 명령어

| 명령 | 기능 |
|---|---|
| `init` / `doctor` | 설정 생성 / 환경 점검 |
| `run-once [--dry-run]` / `daemon` | 1회 실행 / 상시 폴링(+대시보드) |
| `add <id…>` | DOI/arXiv 원샷 추가 (중복 자동 감지) |
| `search <검색어> [--source arxiv\|s2\|crossref]` | 검색 (보유 논문 표시) |
| `queue` / `status` / `trace` | 분석 대기 / 상태 / 감사 로그 |
| `alerts [--fetch\|--approve N]` | arXiv 알림 인박스 |
| `assist` | 소형 로컬모델로 알림 관련도 점수(0–10) 매기기 (옵트인) |
| `enrich` / `related <citekey>` / `synthesis` | 인용그래프·관련추천·클러스터 |
| `install-daemon` | 자동시작: launchd(macOS)/systemd(Linux)/schtasks 안내(Windows) |
| `tray` | 데몬+트레이 아이콘 (`pip install ".[tray]"` 필요) |

## 안전 보장

- Zotero DB·storage에 절대 쓰지 않음 (추가는 Zotero 공식 connector 채널로, Zotero가 스스로 기록)
- 기존 노트 불가침 (`## My Synthesis` 보존), 자동 생성 노트는 AUTO 표시 + ZotVault 소유분만 재생성, 삭제 코드 경로 없음
- 다운로드 예절: OA 우선, 순차+지연+일일한도, 프록시는 더 엄격한 별도 한도 — 학교 IP 차단 방지 설계
- 프록시 인증: 비밀번호 자동화 없음. 브라우저에서 로그인한 세션 쿠키(cookies.txt) 재사용 (Duo 호환). 설정법 `docs/PROXY.md`
- 모든 자동 행동 trace 기록

## Polaris 연동

Polaris 레포의 `polaris/tools/zotvault_tools.py`가 자동 등록됨:
텔레그램에서 "valleytronics 최신 논문 찾아줘" → 검색 결과(보유 표시 포함) → "1, 3번 추가해" → Zotero 추가 → 데몬이 나머지 처리.

## 설치·테스트

README.md(영문) Quick start 참조. 테스트: `python3 -m unittest discover -s tests` (101개, 네트워크 불필요).
