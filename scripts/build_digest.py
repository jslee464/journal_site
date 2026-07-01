#!/usr/bin/env python3
"""
신약개발 저널 다이제스트 생성기.
PubMed(eutils, 공식 API)로 지정 저널의 최근 논문을 수집하고,
OpenAI API로 신약개발 관점의 한국어 요약을 만들어 index.html을 생성한다.

환경변수:
  OPENAI_API_KEY  (필수)  - GitHub Secret으로 주입. 코드에 하드코딩 금지.
  OPENAI_MODEL    (선택)  - 기본 gpt-4o-mini
  NCBI_API_KEY    (선택)  - PubMed 요청 속도 상향
  DIGEST_DAYS     (선택)  - 최근 며칠(기본 8)
  MAX_PER_JOURNAL (선택)  - 저널당 최대 논문 수(기본 4)
"""
import json, os, html, time, urllib.request, urllib.parse
from datetime import datetime
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
NCBI_API_KEY = os.environ.get("NCBI_API_KEY")
DAYS = int(os.environ.get("DIGEST_DAYS", "8"))
MAX_PER_JOURNAL = int(os.environ.get("MAX_PER_JOURNAL", "4"))

# (표시 이름, PubMed [Journal] 약어)
JOURNALS = [
    ("Nature Medicine", "Nat Med"),
    ("Nature Biotechnology", "Nat Biotechnol"),
    ("New England Journal of Medicine", "N Engl J Med"),
    ("Science Translational Medicine", "Sci Transl Med"),
    ("Cell", "Cell"),
    ("Nature", "Nature"),
    ("Science", "Science"),
    ("The Lancet", "Lancet"),
    ("JAMA", "JAMA"),
    ("Nature Reviews Drug Discovery", "Nat Rev Drug Discov"),
    ("Cell Reports Medicine", "Cell Rep Med"),
    ("Nature Cancer", "Nat Cancer"),
]

SKIP_MARKERS = ("retraction", "correction", "erratum", "author correction",
                "reply", "comment on", "editorial", "expression of concern")


def http_get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "journal-digest/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception as e:
            if i == tries - 1:
                raise
            time.sleep(2)


def esearch(term):
    params = {"db": "pubmed", "term": term, "retmax": str(MAX_PER_JOURNAL * 3),
              "sort": "pub_date", "datetype": "pdat", "reldate": str(DAYS), "retmode": "json"}
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    url = EUTILS + "/esearch.fcgi?" + urllib.parse.urlencode(params)
    data = json.loads(http_get(url))
    return data.get("esearchresult", {}).get("idlist", [])


def efetch(pmids):
    params = {"db": "pubmed", "id": ",".join(pmids), "retmode": "xml"}
    if NCBI_API_KEY:
        params["api_key"] = NCBI_API_KEY
    url = EUTILS + "/efetch.fcgi?" + urllib.parse.urlencode(params)
    return http_get(url)


def parse_articles(xml_bytes):
    root = ET.fromstring(xml_bytes)
    out = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID")
        title = " ".join((art.findtext(".//ArticleTitle") or "").split())
        parts = []
        for ab in art.findall(".//Abstract/AbstractText"):
            label = ab.get("Label")
            txt = "".join(ab.itertext()).strip()
            if txt:
                parts.append((f"{label}: " if label else "") + txt)
        abstract = "\n".join(parts).strip()
        authors = []
        for a in art.findall(".//AuthorList/Author"):
            ln, ini = a.findtext("LastName"), a.findtext("Initials")
            if ln:
                authors.append(f"{ln} {ini}" if ini else ln)
        journal = art.findtext(".//Journal/Title") or ""
        year = (art.findtext(".//JournalIssue/PubDate/Year")
                or art.findtext(".//ArticleDate/Year") or "")
        doi = ""
        for eid in art.findall(".//ArticleId"):
            if eid.get("IdType") == "doi":
                doi = eid.text
        out.append(dict(pmid=pmid, title=title, abstract=abstract, authors=authors,
                        journal=journal, year=year, doi=doi))
    return out


def is_research(a):
    t = (a["title"] or "").lower()
    if any(m in t for m in SKIP_MARKERS):
        return False
    return bool(a["abstract"]) and len(a["abstract"]) > 200


def summarize(a):
    prompt = (
        "다음은 학술 논문의 초록이다. 신약개발 융합형 의사과학자를 위해 한국어로 요약하라.\n"
        'JSON으로만 답하라: {"core":"...","detail":"...","tags":["t1","t2","t3"]}\n'
        "- core: 핵심 3~4줄. 무엇을·어떻게·핵심 결과 수치·의미.\n"
        "- detail: 배경/방법/결과/결론 문단. 마지막에 '의사과학자 관점: ...' 한 문장(신약개발·표적·플랫폼 함의).\n"
        "- tags: 분야/논문유형 태그 2~3개(짧은 한국어).\n"
        "- 초록에 없는 수치를 지어내지 말 것.\n\n"
        f"제목: {a['title']}\n저널: {a['journal']}\n초록:\n{a['abstract'][:6000]}"
    )
    body = json.dumps({
        "model": OPENAI_MODEL,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
    }).encode()
    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions", data=body,
        headers={"Authorization": f"Bearer {OPENAI_API_KEY}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        resp = json.loads(r.read())
    return json.loads(resp["choices"][0]["message"]["content"])


def esc(s):
    return html.escape(s or "")


def render(sections, active_names):
    today = datetime.now().strftime("%Y-%m-%d")
    total = sum(len(v) for v in sections.values())
    njournals = sum(1 for v in sections.values() if v)
    chips = ""
    for name, _ in JOURNALS:
        cls = "chip on" if name in active_names else "chip soon"
        chips += f'<span class="{cls}">{esc(name)}</span>\n'

    cards_html = ""
    for name, _abbr in JOURNALS:
        arts = sections.get(name, [])
        if not arts:
            continue
        cards_html += f'<h2 class="jrnl">{esc(name)} <span class="count">· {len(arts)}편</span></h2>\n'
        for a in arts:
            s = a["summary"]
            tags = "".join(f'<span class="tag">{esc(t)}</span>' for t in s.get("tags", [])[:3])
            authors = ", ".join(a["authors"][:3]) + (" et al." if len(a["authors"]) > 3 else "")
            links = f'<a href="https://pubmed.ncbi.nlm.nih.gov/{esc(a["pmid"])}/" target="_blank">PubMed</a>'
            if a["doi"]:
                links += f'<a href="https://doi.org/{esc(a["doi"])}" target="_blank">DOI ↗</a>'
            detail = esc(s.get("detail", "")).replace("\n", "<br>")
            core = esc(s.get("core", "")).replace("\n", "<br>")
            cards_html += f'''
  <div class="card">
    <div class="head" onclick="this.parentNode.classList.toggle('open')">
      <span class="tri">▶</span>
      <div class="t">
        <div class="title">{esc(a["title"])}</div>
        <div class="authors">{esc(authors)} · {esc(a["journal"])} {esc(a["year"])}</div>
        <div class="tags">{tags}</div>
      </div>
    </div>
    <div class="body"><div class="inner">
      <div class="core"><b>핵심 요약</b><br>{core}</div>
      <div class="detail"><h4>상세 요약</h4>{detail}</div>
      <div class="links">{links}</div>
    </div></div>
  </div>'''

    return TEMPLATE.format(today=today, total=total, njournals=njournals,
                           chips=chips, cards=cards_html)


TEMPLATE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>신약개발 저널 다이제스트</title>
<style>
:root{{--bg:#f6f7f9;--card:#fff;--ink:#1a1f2b;--sub:#5b6472;--line:#e6e9ef;--accent:#20558a;--accent2:#0f7b6c;--chip:#eef2f7;--core:#f0f7f4;--coreline:#cfe7de;}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--bg);color:var(--ink);font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;line-height:1.6;}}
.wrap{{max-width:900px;margin:0 auto;padding:32px 20px 80px;}}
header h1{{font-size:27px;margin:0 0 6px;letter-spacing:-.02em;}}
header .meta{{color:var(--sub);font-size:14px;margin-bottom:18px;}}
.banner{{background:#eef6ff;border:1px solid #cfe2f5;border-radius:12px;padding:12px 16px;font-size:13.5px;color:#1c466e;margin-bottom:20px;}}
.setlabel{{font-size:13px;color:var(--sub);margin:0 0 8px;}}
.chips{{display:flex;flex-wrap:wrap;gap:6px;margin-bottom:14px;}}
.chip{{background:var(--chip);border:1px solid var(--line);border-radius:999px;padding:4px 11px;font-size:12.5px;color:#3a4250;}}
.chip.on{{background:#e4eef7;border-color:#bcd6ec;color:#1c4d78;font-weight:600;}}
.chip.on::before{{content:"● ";color:#2f8f6f;font-size:10px;}}
.chip.soon{{opacity:.55;}}
.toolbar{{display:flex;gap:8px;flex-wrap:wrap;margin:8px 0 26px;}}
.toolbar button{{font-size:12.5px;border:1px solid var(--line);background:#fff;border-radius:8px;padding:6px 12px;cursor:pointer;color:#3a4250;}}
.toolbar button:hover{{background:#f0f3f7;}}
h2.jrnl{{font-size:15px;margin:26px 0 10px;padding-bottom:7px;border-bottom:2px solid var(--line);display:flex;align-items:center;gap:8px;}}
h2.jrnl .count{{font-size:12px;color:var(--sub);font-weight:400;}}
.card{{background:var(--card);border:1px solid var(--line);border-radius:12px;margin-bottom:10px;overflow:hidden;transition:box-shadow .15s;}}
.card:hover{{box-shadow:0 2px 10px rgba(20,40,80,.06);}}
.head{{padding:14px 16px;cursor:pointer;display:flex;gap:12px;align-items:flex-start;}}
.head .tri{{color:var(--accent);font-size:12px;margin-top:5px;transition:transform .15s;flex:none;}}
.card.open .tri{{transform:rotate(90deg);}}
.head .t{{flex:1;}}.head .title{{font-size:15.5px;font-weight:650;letter-spacing:-.01em;}}
.head .authors{{font-size:12.5px;color:var(--sub);margin-top:3px;}}
.head .tags{{margin-top:6px;display:flex;flex-wrap:wrap;gap:6px;}}
.tag{{font-size:11px;padding:2px 8px;border-radius:6px;background:#eef2f7;color:#43506a;}}
.body{{max-height:0;overflow:hidden;transition:max-height .3s ease;border-top:1px solid transparent;}}
.card.open .body{{max-height:2600px;border-top-color:var(--line);}}
.inner{{padding:16px;}}
.core{{background:var(--core);border:1px solid var(--coreline);border-radius:10px;padding:12px 14px;font-size:14px;}}
.core b{{color:var(--accent2);}}
.detail{{margin-top:14px;font-size:13.6px;color:#2b3342;}}
.detail h4{{font-size:12px;text-transform:uppercase;letter-spacing:.04em;color:var(--sub);margin:0 0 6px;}}
.links{{margin-top:14px;display:flex;gap:10px;flex-wrap:wrap;}}
.links a{{font-size:12.5px;text-decoration:none;color:var(--accent);border:1px solid #cfe0ef;border-radius:8px;padding:5px 11px;background:#f4f9fd;}}
.links a:hover{{background:#e7f1fa;}}
footer{{margin-top:36px;color:var(--sub);font-size:12px;text-align:center;line-height:1.7;}}
</style></head><body><div class="wrap">
<header><h1>🧬 신약개발 저널 다이제스트</h1>
<div class="meta">융합형 의사과학자용 · 갱신 {today} (매주 월요일 자동) · 출처 PubMed · 요약 OpenAI</div></header>
<div class="banner">지정 핵심 저널의 <b>최신 논문</b>을 자동 수집·요약합니다. 카드를 클릭하면 <b>핵심 3-4줄 요약</b>과 <b>상세 요약</b>·원문 링크가 펼쳐집니다. 이번 갱신 <b>{njournals}개 저널·{total}편</b>.</div>
<p class="setlabel">구독 저널 (● = 이번 갱신 반영)</p>
<div class="chips">{chips}</div>
<div class="toolbar">
<button onclick="document.querySelectorAll('.card').forEach(c=>c.classList.add('open'))">모두 펼치기</button>
<button onclick="document.querySelectorAll('.card').forEach(c=>c.classList.remove('open'))">모두 접기</button></div>
{cards}
<footer>데이터 출처: PubMed (NCBI, 공개 서지정보·초록 기반) · 요약: OpenAI API · 매주 월요일 자동 갱신<br>
유료 저널 전문은 소속 기관 도서관 프록시로 열람하세요. 요약은 공개 초록 기반이며 임상 판단 전 원문 확인을 권장합니다.</footer>
</div></body></html>"""


def main():
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY 환경변수가 없습니다. GitHub Secret에 등록하세요.")
    sections, active = {}, set()
    for name, abbr in JOURNALS:
        try:
            ids = esearch(f'"{abbr}"[Journal]')
            time.sleep(0.4)
            if not ids:
                sections[name] = []
                continue
            arts = parse_articles(efetch(ids))
            time.sleep(0.4)
            picked = [a for a in arts if is_research(a)][:MAX_PER_JOURNAL]
            for a in picked:
                try:
                    a["summary"] = summarize(a)
                except Exception as e:
                    a["summary"] = {"core": "(요약 생성 실패)", "detail": esc(str(e)), "tags": []}
                time.sleep(0.3)
            sections[name] = picked
            if picked:
                active.add(name)
            print(f"[{name}] {len(picked)}편")
        except Exception as e:
            print(f"[{name}] 오류: {e}")
            sections[name] = []
    out = render(sections, active)
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(out)
    print(f"완료: {sum(len(v) for v in sections.values())}편 / index.html 생성")


if __name__ == "__main__":
    main()
