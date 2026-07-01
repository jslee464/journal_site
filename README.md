# 신약개발 저널 다이제스트 (journal_site)

융합형 의사과학자를 위한 주간 저널 다이제스트. 지정 핵심 저널의 최신 논문을
PubMed(eutils API)에서 자동 수집하고, OpenAI API로 신약개발 관점 한국어 요약을
붙여 `index.html`을 생성한다. GitHub Actions가 매주 자동 실행 → 커밋/푸시 →
Vercel 자동 배포까지 무인으로 돈다.

## 구조
- `index.html` — 정적 사이트(단일 파일, 자동 생성).
- `scripts/build_digest.py` — PubMed 수집 + OpenAI 요약 + index.html 생성.
- `.github/workflows/weekly.yml` — 매주 월요일 08:00 KST 자동 실행(+수동 실행 버튼).
- `vercel.json` — Vercel 정적 배포 설정.

## 최초 1회 설정 (사용자)
1. **GitHub Secret 등록**: repo → Settings → Secrets and variables → Actions →
   New repository secret → 이름 `OPENAI_API_KEY`, 값에 본인 OpenAI 키.
   (키를 코드/파일에 절대 넣지 말 것.)
2. **Actions 쓰기 권한**: repo → Settings → Actions → General →
   Workflow permissions → "Read and write permissions" 체크.
3. **Vercel 연결**: vercel.com → New Project → 이 repo import → 설정 없이 Deploy.
   (정적 사이트. Framework Preset: Other, 빌드 명령 없음.)
4. 첫 실행: repo → Actions 탭 → "Weekly Journal Digest" → Run workflow.

## 커스터마이즈
- 저널 목록: `scripts/build_digest.py`의 `JOURNALS` 편집.
- 수집 범위/개수: 워크플로우 env `DIGEST_DAYS`, `MAX_PER_JOURNAL`.
- 요약 모델: env `OPENAI_MODEL`(기본 gpt-4o-mini; 품질 원하면 gpt-4o 등).

## 주의
- 출처: PubMed(공개 서지정보·초록 기반). 유료 전문은 기관 도서관 프록시로 열람.
- 요약은 초록 기반이며 임상 판단 전 원문 확인 권장.
