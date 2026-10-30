"""Сборка HTML-документации из docs/*.md → docs/html/.

Источник правды — Markdown; HTML генерируется и не правится руками:
    make docs        (= uv run python scripts/build_docs.py)

Результат открывается без сервера: docs/html/index.html. Внешних ресурсов нет.
"""

from __future__ import annotations

import html
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

import markdown
from markdown.extensions.toc import slugify_unicode

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"
OUT = DOCS / "html"
BRAND = "max-bot-template"

# Порядок и группы навигации: (файл относительно корня, заголовок, назначение).
# В новом проекте замените разделы своими документами.
SECTIONS: list[tuple[str, list[tuple[str, str, str]]]] = [
    (
        "Работа с ботом",
        [
            ("docs/admin-guide.md", "Руководство администратора", "Доступ и служебные команды"),
            ("README.md", "Запуск и настройка", "Docker, переменные, команды"),
        ],
    ),
    (
        "Разработка",
        [
            ("docs/TEMPLATE.md", "Устройство шаблона", "Архитектура, CI/CD, закрытый контур"),
        ],
    ),
]

# Необязательные исходники: если файла нет, страница просто не попадает в
# навигацию. docs/TEMPLATE.md появляется только после `make init` в проекте,
# созданном из шаблона, — в самом шаблоне это README.md.
OPTIONAL = {"docs/TEMPLATE.md"}
SECTIONS = [
    (group, [item for item in items if item[0] not in OPTIONAL or (ROOT / item[0]).is_file()])
    for group, items in SECTIONS
]

# Значок раздела в навигации и на главной.
ICONS = {
    "docs/admin-guide.md": "🛠", "README.md": "🚀", "docs/TEMPLATE.md": "📐",
}  # fmt: skip

CSS = """
:root{--bg:#f7f5f0;--panel:#fffefb;--ink:#1f2328;--muted:#646b73;--line:#e6e1d7;--line-strong:#d6cfc2;
--accent:#9a3f12;--accent-ink:#7c300b;--accent-soft:#f6e9df;--accent-line:#e9cdb9;--code:#f1eee7;
--mark:#ffe58a;--shadow:0 1px 2px rgba(60,40,20,.05),0 4px 16px rgba(60,40,20,.06);
--radius:12px;--side:280px;--toc:240px}
@media (prefers-color-scheme:dark){:root:not([data-theme="light"]){--bg:#121416;--panel:#1a1d20;
--ink:#e7e4de;--muted:#9ba3ab;--line:#2a2f34;--line-strong:#363c42;--accent:#f2a36b;--accent-ink:#f7bc91;
--accent-soft:#2a1f18;--accent-line:#4a3426;--code:#22262a;--mark:#6b5513;--shadow:0 1px 2px rgba(0,0,0,.3)}}
:root[data-theme="dark"]{--bg:#121416;--panel:#1a1d20;--ink:#e7e4de;--muted:#9ba3ab;--line:#2a2f34;
--line-strong:#363c42;--accent:#f2a36b;--accent-ink:#f7bc91;--accent-soft:#2a1f18;--accent-line:#4a3426;
--code:#22262a;--mark:#6b5513;--shadow:0 1px 2px rgba(0,0,0,.3)}
*{box-sizing:border-box}html{scroll-padding-top:24px;-webkit-text-size-adjust:100%}
body{margin:0;background:var(--bg);color:var(--ink);
font:16.5px/1.65 system-ui,-apple-system,"Segoe UI",Roboto,"Helvetica Neue",sans-serif;
text-rendering:optimizeLegibility;-webkit-font-smoothing:antialiased}
a{color:var(--accent-ink);text-decoration:underline;text-decoration-color:var(--accent-line);
text-underline-offset:3px;text-decoration-thickness:1px}
a:hover{text-decoration-color:currentColor}
:focus-visible{outline:2px solid var(--accent);outline-offset:2px;border-radius:4px}
.layout{display:grid;grid-template-columns:var(--side) minmax(0,1fr);min-height:100vh}

/* Боковая навигация */
.side{position:sticky;top:0;height:100vh;overflow:auto;padding:22px 16px 28px;background:var(--panel);
border-right:1px solid var(--line);display:flex;flex-direction:column;gap:14px}
.brand{display:flex;gap:10px;align-items:center;text-decoration:none;color:var(--ink)}
.brand .logo{flex:none;width:34px;height:34px;border-radius:10px;display:grid;place-items:center;
background:var(--accent);color:#fff;font-size:17px;box-shadow:var(--shadow)}
.brand b{display:block;font-size:14.5px;line-height:1.25}.brand small{color:var(--muted);font-size:12px}
.search{position:relative;display:block}.search input{width:100%;padding:8px 10px 8px 32px;border:1px solid var(--line-strong);
border-radius:9px;background:var(--bg);color:var(--ink);font:inherit;font-size:14px}
.search::before{content:"⌕";position:absolute;left:11px;top:7px;color:var(--muted);font-size:17px;line-height:1.2}
.search .hits{display:block;min-height:16px;margin-top:4px;color:var(--muted);font-size:12px}
.side h4{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin:10px 8px 4px}
.side ul{list-style:none;margin:0;padding:0}
.side li a{display:flex;gap:8px;align-items:center;padding:6px 8px;border-radius:8px;color:var(--ink);
text-decoration:none;font-size:14px;line-height:1.35}
.side li a .ic{width:20px;text-align:center;flex:none}
.side li a:hover{background:var(--accent-soft)}
.side li a.active{background:var(--accent-soft);color:var(--accent-ink);font-weight:600;
box-shadow:inset 3px 0 0 var(--accent)}
.side .tools{margin-top:auto;display:flex;gap:8px;align-items:center;color:var(--muted);font-size:12px}
.btn{border:1px solid var(--line-strong);background:var(--panel);color:var(--ink);border-radius:8px;
padding:6px 10px;font:inherit;font-size:13px;cursor:pointer}
.btn:hover{border-color:var(--accent)}

/* Страница */
.content{min-width:0;padding:36px clamp(16px,4vw,56px) 64px}
.page{display:grid;grid-template-columns:minmax(0,800px) var(--toc);gap:48px;justify-content:start}
.page.wide{grid-template-columns:minmax(0,1040px)}
article{min-width:0}
.eyebrow{display:inline-flex;gap:6px;align-items:center;font-size:12.5px;font-weight:600;letter-spacing:.04em;
color:var(--accent-ink);background:var(--accent-soft);border:1px solid var(--accent-line);
padding:3px 10px;border-radius:999px;margin-bottom:14px}
h1{font-size:clamp(26px,3.2vw,34px);line-height:1.18;letter-spacing:-.015em;margin:0 0 18px;text-wrap:balance}
h2{font-size:23px;line-height:1.25;letter-spacing:-.01em;margin:48px 0 12px;padding-top:20px;border-top:1px solid var(--line)}
h3{font-size:18.5px;margin:32px 0 8px}
h1 a.anchor,h2 a.anchor,h3 a.anchor{opacity:0;margin-left:8px;text-decoration:none;color:var(--muted);font-weight:400}
h1:hover a.anchor,h2:hover a.anchor,h3:hover a.anchor{opacity:1}
p,ul,ol{margin:0 0 14px}li{margin:3px 0}li>ul,li>ol{margin:4px 0 0}
strong{font-weight:650}
code{font:.86em/1.5 ui-monospace,SFMono-Regular,"JetBrains Mono",Menlo,Consolas,monospace;
background:var(--code);padding:2px 6px;border-radius:5px;overflow-wrap:anywhere}
pre{position:relative;background:var(--code);border:1px solid var(--line);border-radius:10px;
padding:14px 16px;overflow:auto;margin:16px 0}
pre code{padding:0;background:none;font-size:13.5px;overflow-wrap:normal}
pre .copy{position:absolute;top:8px;right:8px;opacity:0;transition:opacity .15s}
pre:hover .copy,pre .copy:focus-visible{opacity:1}
.table{overflow-x:auto;margin:18px 0;border:1px solid var(--line);border-radius:var(--radius);
background:var(--panel);box-shadow:var(--shadow)}
table{border-collapse:collapse;width:100%;font-size:14.5px}
th,td{text-align:left;vertical-align:top;padding:10px 12px;border-bottom:1px solid var(--line)}
th{background:var(--accent-soft);font-weight:650;font-size:13.5px;white-space:nowrap}
tbody tr:nth-child(even) td{background:color-mix(in srgb,var(--bg) 55%,transparent)}
tbody tr:hover td{background:var(--accent-soft)}tr:last-child td{border-bottom:0}
td code{font-size:.82em}
blockquote{margin:18px 0;padding:12px 16px;border:1px solid var(--accent-line);border-left:4px solid var(--accent);
background:var(--accent-soft);border-radius:10px}blockquote p:last-child{margin:0}
hr{border:0;border-top:1px solid var(--line);margin:32px 0}
mark{background:var(--mark);color:inherit;border-radius:3px;padding:0 1px}
mark.current{outline:2px solid var(--accent)}

/* Оглавление справа */
.otp{position:sticky;top:28px;align-self:start;max-height:calc(100vh - 56px);overflow:auto;font-size:13.5px;
padding-left:16px;border-left:1px solid var(--line)}
.otp b{display:block;font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--muted);margin-bottom:8px}
.otp ul{list-style:none;margin:0;padding:0}.otp ul ul{padding-left:12px}
.otp li{margin:0}.otp a{display:block;padding:4px 0;color:var(--muted);text-decoration:none;line-height:1.35}
.otp a:hover{color:var(--ink)}.otp a.on{color:var(--accent-ink);font-weight:600}
.toc-inline{display:none;border:1px solid var(--line);border-radius:var(--radius);background:var(--panel);
margin:0 0 24px;font-size:14.5px}
.toc-inline summary{cursor:pointer;padding:10px 14px;font-weight:600;list-style:none}
.toc-inline summary::-webkit-details-marker{display:none}
.toc-inline summary::before{content:"▸ ";color:var(--muted)}.toc-inline[open] summary::before{content:"▾ "}
.toc-inline ul{margin:0;padding:0 14px 12px 30px}.toc-inline ul ul{padding:2px 0 0 16px}

/* Главная */
.hero{padding:28px 28px 26px;margin:0 0 28px;border:1px solid var(--accent-line);border-radius:18px;
background:radial-gradient(120% 140% at 100% 0%,var(--accent-soft) 0%,var(--panel) 60%);box-shadow:var(--shadow)}
.hero h1{margin:6px 0 10px}.hero p{margin:0;color:var(--muted);max-width:640px;font-size:17px}
.hero .actions{display:flex;flex-wrap:wrap;gap:10px;margin-top:18px}
.hero .actions a{text-decoration:none;padding:8px 14px;border-radius:10px;font-weight:600;font-size:14.5px;
border:1px solid var(--line-strong);color:var(--ink);background:var(--panel)}
.hero .actions a.primary{background:var(--accent);border-color:var(--accent);color:#fff}
.cards{display:grid;grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:14px;margin:12px 0 28px}
.card{display:flex;gap:12px;align-items:flex-start;border:1px solid var(--line);border-radius:var(--radius);
padding:16px;background:var(--panel);text-decoration:none;color:var(--ink);box-shadow:var(--shadow);
transition:border-color .15s,transform .15s}
.card:hover{border-color:var(--accent);transform:translateY(-1px)}
.card .ic{font-size:22px;line-height:1}.card b{display:block;margin-bottom:3px;color:var(--accent-ink)}
.card span{color:var(--muted);font-size:14px;line-height:1.45}

/* Соседние страницы и подвал */
.pager{display:grid;grid-template-columns:1fr 1fr;gap:14px;margin-top:56px}
.pager a{display:block;padding:14px 16px;border:1px solid var(--line);border-radius:var(--radius);
text-decoration:none;color:var(--ink);background:var(--panel)}
.pager a:hover{border-color:var(--accent)}.pager small{display:block;color:var(--muted);font-size:12.5px}
.pager a.next{text-align:right;grid-column:2}
footer{color:var(--muted);font-size:13px;margin-top:40px;padding-top:16px;border-top:1px solid var(--line)}
.menu-btn{display:none}
.top{position:fixed;right:18px;bottom:18px;opacity:0;pointer-events:none;transition:opacity .2s;box-shadow:var(--shadow)}
.top.show{opacity:1;pointer-events:auto}

@media (max-width:1240px){.page{grid-template-columns:minmax(0,820px)}.otp{display:none}
.toc-inline{display:block}}
@media (max-width:880px){.layout{grid-template-columns:1fr}
.side{position:fixed;inset:0 auto 0 0;width:min(86vw,320px);z-index:20;transform:translateX(-105%);
transition:transform .2s;box-shadow:var(--shadow)}
.side.open{transform:none}
.menu-btn{display:inline-flex;position:sticky;top:0;z-index:10;margin:0;width:100%;border-radius:0;
border-width:0 0 1px;padding:12px 16px;background:var(--panel)}
.content{padding:20px 16px 48px}.hero{padding:20px}.pager{grid-template-columns:1fr}.pager a.next{grid-column:1}
h2{font-size:21px}}
@media (prefers-reduced-motion:reduce){*{transition:none!important;scroll-behavior:auto!important}}
@media print{.side,.menu-btn,.otp,.toc-inline,.pager,.top,pre .copy{display:none!important}
.layout,.page{display:block}.content{padding:0}.table,.card,.hero{box-shadow:none}}
"""

JS = """
(()=>{
const root=document.documentElement,store={get(k){try{return localStorage.getItem(k)}catch(e){return null}},
set(k,v){try{localStorage.setItem(k,v)}catch(e){}}};
const saved=store.get('docs-theme');if(saved)root.dataset.theme=saved;
const tb=document.getElementById('theme');
if(tb){const dark=()=>root.dataset.theme?root.dataset.theme==='dark':matchMedia('(prefers-color-scheme:dark)').matches;
const label=()=>{tb.textContent=dark()?'☀ Светлая':'☾ Тёмная'};label();
tb.onclick=()=>{root.dataset.theme=dark()?'light':'dark';store.set('docs-theme',root.dataset.theme);label()}}
const q=document.getElementById('q'),hitsEl=document.getElementById('hits');let marks=[],cur=-1;
function clearMarks(){document.querySelectorAll('article mark').forEach(m=>m.replaceWith(...m.childNodes));
document.querySelector('article').normalize();marks=[];cur=-1}
function go(i){if(!marks.length)return;if(cur>=0)marks[cur].classList.remove('current');cur=(i+marks.length)%marks.length;
marks[cur].classList.add('current');marks[cur].scrollIntoView({block:'center'});
hitsEl.textContent=(cur+1)+' из '+marks.length+' · Enter — дальше'}
if(q){q.addEventListener('input',()=>{clearMarks();const v=q.value.trim().toLowerCase();hitsEl.textContent='';
if(v.length<2)return;const w=document.createTreeWalker(document.querySelector('article'),NodeFilter.SHOW_TEXT);
const nodes=[];let n;while(n=w.nextNode()){if(n.parentElement.closest('pre .copy'))continue;
if(n.nodeValue.toLowerCase().includes(v))nodes.push(n)}
nodes.slice(0,300).forEach(t=>{let node=t;let i;while(node&&(i=node.nodeValue.toLowerCase().indexOf(v))>-1){
const r=document.createRange();r.setStart(node,i);r.setEnd(node,i+v.length);const m=document.createElement('mark');
r.surroundContents(m);marks.push(m);node=m.nextSibling&&m.nextSibling.nodeType===3?m.nextSibling:null}});
if(marks.length)go(0);else hitsEl.textContent='Не найдено'});
q.addEventListener('keydown',e=>{if(e.key==='Enter'){e.preventDefault();go(cur+(e.shiftKey?-1:1))}
if(e.key==='Escape'){q.value='';clearMarks();hitsEl.textContent=''}})}
document.addEventListener('keydown',e=>{if(e.key==='/'&&document.activeElement!==q&&q){e.preventDefault();q.focus()}});
document.querySelectorAll('article pre').forEach(pre=>{const b=document.createElement('button');
b.className='btn copy';b.type='button';b.textContent='Копировать';b.onclick=()=>{
const t=pre.querySelector('code').innerText;const done=()=>{b.textContent='Скопировано';setTimeout(()=>b.textContent='Копировать',1500)};
if(navigator.clipboard)navigator.clipboard.writeText(t).then(done,()=>{});};pre.appendChild(b)});
const links=[...document.querySelectorAll('.otp a')],heads=links.map(a=>document.getElementById(decodeURIComponent(a.hash.slice(1)))).filter(Boolean);
if(heads.length&&'IntersectionObserver' in window){const io=new IntersectionObserver(es=>{es.forEach(e=>{if(e.isIntersecting){
links.forEach(a=>a.classList.toggle('on',decodeURIComponent(a.hash.slice(1))===e.target.id))}})},{rootMargin:'0px 0px -70% 0px'});heads.forEach(h=>io.observe(h))}
const side=document.querySelector('.side'),mb=document.querySelector('.menu-btn');
if(mb){mb.onclick=e=>{e.stopPropagation();side.classList.toggle('open')};
document.addEventListener('click',e=>{if(side.classList.contains('open')&&!side.contains(e.target))side.classList.remove('open')})}
const up=document.querySelector('.top');if(up){addEventListener('scroll',()=>up.classList.toggle('show',scrollY>900),{passive:true});
up.onclick=()=>scrollTo({top:0,behavior:'smooth'})}
})();
"""


def out_name(src: str) -> str:
    return "index.html" if src == "README.md" else Path(src).stem + ".html"


def page_map() -> dict[str, str]:
    """Путь исходника (как его пишут в тексте) → имя HTML-страницы."""
    mapping = {}
    for _, items in SECTIONS:
        for src, _, _ in items:
            mapping[src] = out_name(src)
            mapping[Path(src).name] = out_name(src)
    return mapping


def link_docs(body: str, mapping: dict[str, str]) -> str:
    """Упоминания `docs/…md` в тексте и ссылки на .md превращаются в ссылки на страницы."""

    def code_ref(m: re.Match[str]) -> str:
        target = mapping.get(html.unescape(m.group(1)))
        return f'<a href="{target}"><code>{m.group(1)}</code></a>' if target else m.group(0)

    body = re.sub(r"<code>((?:docs/)?[\w./-]+\.md)</code>", code_ref, body)
    body = re.sub(
        r'href="((?:\.\./|docs/)*)([\w./-]+\.md)"',
        lambda m: (
            f'href="{mapping.get(m.group(2), mapping.get(Path(m.group(2)).name, m.group(2)))}"'
        ),
        body,
    )

    # Голые пути «docs/x.md» в обычном тексте (вне тегов и ссылок).
    def bare(m: re.Match[str]) -> str:
        target = mapping.get(m.group(0))
        return f'<a href="{target}">{m.group(0)}</a>' if target else m.group(0)

    parts = re.split(r"(<a\b[^>]*>.*?</a>|<pre>.*?</pre>|<[^>]+>)", body, flags=re.S)
    return "".join(
        p if p.startswith("<") else re.sub(r"(?:docs/)?[\w-]+(?:/[\w-]+)*\.md", bare, p)
        for p in parts
    )


def render(src: Path) -> tuple[str, str, str]:
    """(заголовок, html тела, html оглавления)."""
    md = markdown.Markdown(
        extensions=["tables", "fenced_code", "toc", "sane_lists"],
        extension_configs={
            "toc": {
                "permalink": "#",
                "permalink_class": "anchor",
                "toc_depth": "2-3",
                # Якоря с кириллицей: #вход-и-роли, а не #_1.
                "slugify": slugify_unicode,
            }
        },
    )
    body = md.convert(src.read_text(encoding="utf-8"))
    body = body.replace("<table>", '<div class="table"><table>').replace(
        "</table>", "</table></div>"
    )
    match = re.search(r"<h1[^>]*>(.*?)<a class=\"anchor\"", body, re.S)
    title = re.sub(r"<[^>]+>", "", match.group(1)).strip() if match else src.stem
    return title, body, md.toc  # type: ignore[attr-defined]


def nav(active: str) -> str:
    out = []
    for group, items in SECTIONS:
        out.append(f"<h4>{html.escape(group)}</h4><ul>")
        for src, label, about in items:
            name = out_name(src)
            cls = ' class="active"' if name == active else ""
            out.append(
                f'<li><a href="{name}"{cls} title="{html.escape(about)}">'
                f'<span class="ic">{ICONS.get(src, "📄")}</span>{html.escape(label)}</a></li>'
            )
        out.append("</ul>")
    return "".join(out)


def flat_pages() -> list[tuple[str, str, str]]:
    """(файл, заголовок, группа) в порядке навигации — для «назад/далее»."""
    return [(src, label, group) for group, items in SECTIONS for src, label, _ in items]


def pager(name: str) -> str:
    pages = flat_pages()
    idx = next(i for i, (src, _, _) in enumerate(pages) if out_name(src) == name)
    out = []
    if idx > 0:
        src, label, _ = pages[idx - 1]
        out.append(f'<a href="{out_name(src)}"><small>← Назад</small>{html.escape(label)}</a>')
    if idx < len(pages) - 1:
        src, label, _ = pages[idx + 1]
        out.append(
            f'<a class="next" href="{out_name(src)}"><small>Далее →</small>{html.escape(label)}</a>'
        )
    return f'<nav class="pager" aria-label="Соседние страницы">{"".join(out)}</nav>'


def page(name: str, title: str, article: str, toc: str, stamp: str) -> str:
    # Markdown оборачивает оглавление в <div class="toc"> — берём только список.
    toc_list = re.sub(r'^\s*<div class="toc">\s*|\s*</div>\s*$', "", toc or "")
    has_toc = toc_list.count("<li>") > 2 and name != "index.html"
    group = next((g for src, _, g in flat_pages() if out_name(src) == name), "")
    eyebrow = (
        f'<span class="eyebrow">{html.escape(group)}</span>'
        if group and name != "index.html"
        else ""
    )
    inline = (f'<details class="toc-inline"><summary>Содержание</summary>{toc_list}</details>'
              if has_toc else "")  # fmt: skip
    side_toc = (
        f'<aside class="otp" aria-label="На этой странице"><b>На этой странице</b>{toc_list}</aside>'
        if has_toc
        else ""
    )
    body = _before_title(article, eyebrow)
    body = _after_title(body, inline)
    doc_title = BRAND if name == "index.html" else f"{title} — {BRAND}"
    return f"""<!doctype html>
<html lang="ru"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="color-scheme" content="light dark">
<title>{html.escape(doc_title)}</title>
<link rel="stylesheet" href="style.css">
<link rel="icon" href="data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'%3E%3Crect width='16' height='16' rx='4' fill='%239a3f12'/%3E%3Cpath d='M8 3.2a3 3 0 0 0-3 3c0 2.3 3 6.2 3 6.2s3-3.9 3-6.2a3 3 0 0 0-3-3zm0 4.2a1.2 1.2 0 1 1 0-2.4 1.2 1.2 0 0 1 0 2.4z' fill='%23fff'/%3E%3C/svg%3E"></head>
<body><div class="layout">
<button class="btn menu-btn" type="button" aria-label="Открыть меню разделов">☰ {html.escape(BRAND)}</button>
<nav class="side" aria-label="Разделы документации">
<a class="brand" href="index.html"><span class="logo">💬</span><span><b>{html.escape(BRAND)}</b><small>Документация · MAX</small></span></a>
<label class="search"><input id="q" type="search" placeholder="Найти на странице  ( / )" aria-label="Найти на странице"><span class="hits" id="hits" aria-live="polite"></span></label>
{nav(name)}
<div class="tools"><button class="btn" id="theme" type="button">Тема</button></div>
</nav>
<main class="content"><div class="page{"" if has_toc else " wide"}"><article>{body}{pager(name)}</article>{side_toc}</div>
<footer>Собрано из Markdown {stamp} · <code>make docs</code> · источник — <code>docs/*.md</code></footer></main>
</div><button class="btn top" type="button" aria-label="Наверх">↑ Наверх</button>
<script>{JS}</script></body></html>
"""


def _before_title(article: str, block: str) -> str:
    """Вставляет блок перед заголовком страницы (h1)."""
    if not block or "<h1" not in article:
        return article
    i = article.index("<h1")
    return article[:i] + block + article[i:]


def _after_title(article: str, block: str) -> str:
    """Вставляет блок сразу после заголовка страницы (h1)."""
    if not block or "</h1>" not in article:
        return block + article
    return article.replace("</h1>", "</h1>" + block, 1)


def index_cards() -> str:
    out = ['<h2 id="docs">Разделы документации</h2>']
    for group, items in SECTIONS:
        out.append(f'<h3>{html.escape(group)}</h3><div class="cards">')
        for src, label, about in items:
            out.append(
                f'<a class="card" href="{out_name(src)}"><span class="ic">{ICONS.get(src, "📄")}</span>'
                f"<span><b>{html.escape(label)}</b><span>{html.escape(about)}</span></span></a>"
            )
        out.append("</div>")
    return "".join(out)


def index_hero(body: str) -> str:
    """Заголовок README и вводный абзац → шапка главной с быстрыми ссылками."""
    head = re.search(r"<h1[^>]*>.*?</h1>\s*(<p>.*?</p>)?", body, re.S)
    if not head:
        return body
    lead = head.group(1) or ""
    hero = (
        '<section class="hero"><span class="eyebrow">Документация · max-bot-template</span>'
        f"<h1>{html.escape(BRAND)}</h1>{lead}"
        '<div class="actions"><a class="primary" href="admin-guide.html">🛠 Руководство администратора</a>'
        '<a href="#быстрый-старт">🚀 Быстрый старт</a></div>'
        "</section>"
    )
    return body[: head.start()] + hero + index_cards() + body[head.end() :]


def build() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    mapping = page_map()
    stamp = datetime.now(UTC).astimezone().strftime("%d.%m.%Y %H:%M")
    missing = []
    for _, items in SECTIONS:
        for src, _, _ in items:
            path = ROOT / src
            if not path.is_file():
                missing.append(src)
                continue
            title, body, toc = render(path)
            body = link_docs(body, mapping)
            name = out_name(src)
            if name == "index.html":
                body = index_hero(body)
            (OUT / name).write_text(page(name, title, body, toc, stamp), encoding="utf-8")
    (OUT / "style.css").write_text(CSS.strip() + "\n", encoding="utf-8")
    if missing:
        print("Нет исходников: " + ", ".join(missing), file=sys.stderr)
        return 1
    print(f"Документация собрана: {OUT.relative_to(ROOT)}/index.html")
    return 0


if __name__ == "__main__":
    sys.exit(build())
