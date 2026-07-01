#!/usr/bin/env python3
"""
Drug Development Digest 생성기.
PubMed(eutils)로 지정 저널의 최근 한 달 논문을 수집하고,
OpenAI API로 신약개발 관점의 한국어 요약을 만들어 index.html을 생성한다.

환경변수:
  OPENAI_API_KEY  (필수)  - GitHub Secret으로 주입. 코드에 하드코딩 금지.
  OPENAI_MODEL    (선택)  - 기본 gpt-4o-mini
  NCBI_API_KEY    (선택)  - PubMed 요청 속도 상향
  DIGEST_DAYS     (선택)  - 최근 며칠(기본 31, 최근 한 달)
  MAX_PER_JOURNAL (선택)  - 저널당 최대 논문 수 안전상한(기본 25)
"""
import json, os, html, time, re, urllib.request, urllib.parse
from datetime import datetime
import xml.etree.ElementTree as ET

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY")
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
NCBI_API_KEY = os.environ.get("NCBI_API_KEY")
DAYS = int(os.environ.get("DIGEST_DAYS", "31"))
MAX_PER_JOURNAL = int(os.environ.get("MAX_PER_JOURNAL", "25"))

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


def slug(name):
    return re.sub(r'[^a-z0-9]+', '-', name.lower()).strip('-')


def http_get(url, tries=3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "ddd/1.0"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except Exception:
            if i == tries - 1:
                raise
            time.sleep(2)


def esearch(term):
    # sort=pub_date -> 최신 게재순(내림차순). reldate=DAYS -> 최근 한 달.
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
    out = {}
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
        out[pmid] = dict(pmid=pmid, title=title, abstract=abstract, authors=authors,
                         journal=journal, year=year, doi=doi)
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


def card_html(a):
    s = a["summary"]
    tags = s.get("tags", [])[:3]
    tag_html = ""
    for i, t in enumerate(tags):
        cls = "tag type" if i == len(tags) - 1 and len(tags) > 1 else "tag"
        tag_html += f'<span class="{cls}">{esc(t)}</span>'
    authors = ", ".join(a["authors"][:3]) + (" et al." if len(a["authors"]) > 3 else "")
    links = f'<a href="https://pubmed.ncbi.nlm.nih.gov/{esc(a["pmid"])}/" target="_blank">PubMed</a>'
    if a["doi"]:
        links += f'<a href="https://doi.org/{esc(a["doi"])}" target="_blank">DOI ↗</a>'
    core = esc(s.get("core", "")).replace("\n", "<br>")
    detail = esc(s.get("detail", "")).replace("\n", "<br>")
    return f'''
  <div class="card">
    <div class="head" onclick="this.parentNode.classList.toggle('open')">
      <span class="tri">▶</span>
      <div>
        <div class="title">{esc(a["title"])}</div>
        <div class="authors">{esc(authors)} · {esc(a["journal"])} {esc(a["year"])}</div>
        <div class="tags">{tag_html}</div>
      </div>
    </div>
    <div class="body"><div class="inner">
      <div class="core"><b>핵심 요약</b><br>{core}</div>
      <div class="detail"><h4>상세 요약</h4>{detail}</div>
      <div class="links">{links}</div>
    </div></div>
  </div>'''


def render(sections):
    today = datetime.now().strftime("%Y-%m-%d")
    total = sum(len(v) for v in sections.values())
    active = [(name, slug(name)) for name, _ in JOURNALS if sections.get(name)]
    njournals = len(active)

    chips = ""
    for name, _ in JOURNALS:
        if sections.get(name):
            chips += f'<a class="chip" href="#{slug(name)}">{esc(name)}</a>\n'
        else:
            chips += f'<span class="chip soon">{esc(name)}</span>\n'

    secs = ""
    for name, _ in JOURNALS:
        arts = sections.get(name, [])
        if not arts:
            continue
        secs += (f'<section id="{slug(name)}" class="jrnl"><span class="tick"></span>'
                 f'<h2>{esc(name)}</h2><span class="count">{len(arts)}편</span></section>\n')
        for a in arts:  # 이미 최신 게재순(내림차순)
            secs += card_html(a)

    return (TEMPLATE.replace('%%TODAY%%', today).replace('%%N%%', str(njournals))
            .replace('%%TOTAL%%', str(total)).replace('%%CHIPS%%', chips)
            .replace('%%SECTIONS%%', secs))


TEMPLATE = """<!DOCTYPE html>
<html lang="ko"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Drug Development Digest</title>
<style>
  :root{
    --bg:#faf9f5; --surface:#ffffff; --surface2:#f3f1ea;
    --border:#e7e3d8; --border-soft:#efece2;
    --text:#23221c; --sub:#6b6960; --dim:#97948a;
    --accent:#c15f3c; --accent-strong:#a44d2d;
    --accent-soft:rgba(193,95,60,.08); --accent-border:rgba(193,95,60,.30);
    --core-bg:#f8f3ef;
  }
  *{box-sizing:border-box}
  html{scroll-behavior:smooth}
  body{margin:0;background:var(--bg);color:var(--text);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,"Apple SD Gothic Neo","Malgun Gothic",sans-serif;
    line-height:1.65;-webkit-font-smoothing:antialiased;}
  .wrap{max-width:920px;margin:0 auto;padding:0 20px 100px;}
  header{text-align:center;padding:56px 0 26px;}
  header .brand{font-family:Georgia,"Times New Roman",serif;font-size:38px;
    letter-spacing:-.5px;font-weight:600;color:var(--text);margin:0;}
  header .brand .accent{color:var(--accent);}
  header .sub{margin:12px 0 0;font-size:15px;color:var(--sub);}
  header .meta{margin:14px 0 0;font-size:12.5px;color:var(--dim);letter-spacing:.02em;}
  header .rule{width:44px;height:3px;background:var(--accent);border-radius:2px;margin:22px auto 0;opacity:.9;}
  .subnav{position:sticky;top:0;z-index:20;background:rgba(250,249,245,.86);
    backdrop-filter:blur(10px);border-bottom:1px solid var(--border-soft);
    margin:0 -20px;padding:12px 20px;}
  .subnav .inner{max-width:920px;margin:0 auto;display:flex;flex-wrap:wrap;gap:7px;justify-content:center;}
  .chip{font-size:12.5px;padding:5px 12px;border-radius:999px;border:1px solid var(--border);
    background:var(--surface);color:var(--sub);text-decoration:none;transition:all .15s;white-space:nowrap;}
  a.chip{cursor:pointer;}
  a.chip::before{content:"";display:inline-block;width:6px;height:6px;border-radius:50%;
    background:var(--accent);margin-right:7px;vertical-align:middle;}
  a.chip:hover{border-color:var(--accent-border);color:var(--text);background:var(--accent-soft);}
  .chip.soon{opacity:.45;}
  .jrnl{scroll-margin-top:70px;margin:38px 0 12px;display:flex;align-items:baseline;gap:10px;
    padding-bottom:10px;border-bottom:1px solid var(--border);}
  .jrnl h2{font-size:15px;font-weight:600;margin:0;color:var(--text);letter-spacing:.01em;}
  .jrnl .tick{width:3px;height:15px;background:var(--accent);border-radius:2px;align-self:center;}
  .jrnl .count{font-size:12px;color:var(--dim);}
  .card{background:var(--surface);border:1px solid var(--border);border-radius:12px;
    margin-bottom:11px;overflow:hidden;transition:border-color .15s,box-shadow .15s;}
  .card:hover{border-color:#d9d4c7;box-shadow:0 1px 4px rgba(60,50,30,.05);}
  .head{padding:15px 17px;cursor:pointer;display:flex;gap:12px;align-items:flex-start;}
  .head .tri{color:var(--accent);font-size:11px;margin-top:6px;flex:none;transition:transform .18s;}
  .card.open .tri{transform:rotate(90deg);}
  .head .title{font-size:15.5px;font-weight:600;color:var(--text);letter-spacing:-.01em;}
  .head .authors{font-size:12.5px;color:var(--sub);margin-top:4px;}
  .head .tags{margin-top:8px;display:flex;flex-wrap:wrap;gap:6px;}
  .tag{font-size:11px;padding:2px 9px;border-radius:6px;background:var(--surface2);
    color:#74726a;border:1px solid var(--border-soft);}
  .tag.type{color:var(--accent);border-color:var(--accent-border);background:var(--accent-soft);}
  .body{max-height:0;overflow:hidden;transition:max-height .28s ease;}
  .card.open .body{max-height:2600px;}
  .inner{padding:0 17px 17px;}
  .core{background:var(--core-bg);border:1px solid var(--accent-border);border-radius:10px;
    padding:13px 15px;font-size:13.8px;color:var(--text);}
  .core b{color:var(--accent);font-weight:600;}
  .detail{margin-top:14px;font-size:13.4px;color:var(--sub);}
  .detail h4{font-size:11px;text-transform:uppercase;letter-spacing:.06em;color:var(--dim);margin:0 0 7px;}
  .detail i{color:var(--accent-strong);font-style:normal;font-weight:600;}
  .links{margin-top:15px;display:flex;gap:9px;flex-wrap:wrap;}
  .links a{font-size:12.5px;text-decoration:none;color:var(--accent);border:1px solid var(--accent-border);
    border-radius:8px;padding:6px 12px;transition:background .15s;}
  .links a:hover{background:var(--accent-soft);}
  footer{margin-top:44px;padding-top:20px;border-top:1px solid var(--border-soft);
    color:var(--dim);font-size:12px;text-align:center;line-height:1.8;}
</style></head><body><div class="wrap">
<header>
  <h1 class="brand">Drug Development <span class="accent">Digest</span></h1>
  <p class="sub">신약개발 융합형 의사과학자를 위한 논문 브리핑</p>
  <p class="meta">UPDATED %%TODAY%% · 최근 한 달 · %%N%%개 저널 · %%TOTAL%%편 · SOURCE PubMed · SUMMARY OpenAI</p>
  <div class="rule"></div>
</header>
<nav class="subnav"><div class="inner">
%%CHIPS%%
</div></nav>
%%SECTIONS%%
<footer>데이터 출처 PubMed · 요약 OpenAI · 매주 월요일 자동 갱신 · 최근 한 달 게재분(저널별 최신순)<br>
유료 저널 전문은 소속 기관 도서관 프록시로 열람하세요. 요약은 공개 초록 기반입니다.</footer>
</div>
<script>
document.querySelectorAll('a.chip').forEach(function(a){
  a.addEventListener('click', function(e){
    e.preventDefault();
    var el = document.querySelector(this.getAttribute('href'));
    if(el) el.scrollIntoView({behavior:'smooth', block:'start'});
  });
});
</script>
</body></html>"""


def main():
    if not OPENAI_API_KEY:
        raise SystemExit("OPENAI_API_KEY 환경변수가 없습니다. GitHub Secret에 등록하세요.")
    sections = {}
    for name, abbr in JOURNALS:
        try:
            ids = esearch(f'"{abbr}"[Journal]')  # 최신 게재순
            time.sleep(0.4)
            if not ids:
                sections[name] = []
                continue
            by_pmid = parse_articles(efetch(ids))
            time.sleep(0.4)
            ordered = [by_pmid[p] for p in ids if p in by_pmid]  # 최신 -> 오래된 순 유지
            picked = [a for a in ordered if is_research(a)][:MAX_PER_JOURNAL]
            for a in picked:
                try:
                    a["summary"] = summarize(a)
                except Exception as e:
                    a["summary"] = {"core": "(요약 생성 실패)", "detail": esc(str(e)), "tags": []}
                time.sleep(0.3)
            sections[name] = picked
            print(f"[{name}] {len(picked)}편")
        except Exception as e:
            print(f"[{name}] 오류: {e}")
            sections[name] = []
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(render(sections))
    print(f"완료: {sum(len(v) for v in sections.values())}편 / index.html 생성")


if __name__ == "__main__":
    main()
