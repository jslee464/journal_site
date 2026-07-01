# 신약개발 저널 다이제스트 (journal_site)

융합형 의사과학자를 위한 주간 저널 다이제스트. 지정한 핵심 저널의 최신 논문을
PubMed에서 자동 수집하여 신약개발 관점의 요약(핵심 3-4줄 + 상세)과 함께 보여준다.

## 구성
- `index.html` — 정적 사이트(단일 파일). 저널별 목록, 클릭 시 요약 펼침.
- `vercel.json` — Vercel 정적 배포 설정(빌드 불필요).

## 갱신
매주 월요일 아침, Claude Cowork의 예약 작업이 PubMed에서 새 논문을 수집·요약해
`index.html`을 다시 생성한다.

## 배포 (Vercel)
1. 이 repo를 GitHub에 push
2. vercel.com → New Project → 이 repo import → 설정 없이 Deploy
   (정적 사이트라 Framework Preset: Other, 빌드 명령 없음)

## 데이터/주의
- 출처: PubMed (NCBI, 공개 서지정보·초록 기반)
- 유료 저널 전문은 소속 기관 도서관 프록시로 열람. 요약은 초록 기반이며 임상 판단 전 원문 확인 권장.
