"""OpenGriffin dashboard web server.

Serves a d3 force-directed skill graph plus journal and usage panels.

Run standalone:
    python -m opengriffin.dashboard.server
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any

from aiohttp import web

SKILLS_ROOT = Path.home() / ".claude" / "skills"
JOURNAL_FILE = Path.home() / ".opengriffin" / "memories" / "JOURNAL.md"
USAGE_FILE = Path.home() / ".opengriffin" / "usage.jsonl"


# ---------------------------------------------------------------------------
# data loading
# ---------------------------------------------------------------------------


def _parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    """Parse a leading YAML-ish frontmatter block. Returns (mapping, body)."""
    if not text.startswith("---"):
        return {}, text
    end = text.find("\n---", 3)
    if end < 0:
        return {}, text
    fm_text = text[3:end].strip()
    body = text[end + 4 :].lstrip("\n")

    fm: dict[str, Any] = {}
    current_key: str | None = None
    for raw in fm_text.splitlines():
        if not raw.strip():
            continue
        if raw[:1] in (" ", "\t") and current_key:
            val = raw.strip().lstrip("- ").strip().strip('"').strip("'")
            existing = fm.get(current_key)
            if isinstance(existing, list):
                existing.append(val)
            elif existing in (None, ""):
                fm[current_key] = [val]
            else:
                fm[current_key] = [existing, val]
            continue
        if ":" in raw:
            k, _, v = raw.partition(":")
            v = v.strip().strip('"').strip("'")
            current_key = k.strip()
            fm[current_key] = v
    return fm, body


def _usage_counts_by_skill() -> dict[str, int]:
    counts: dict[str, int] = {}
    if not USAGE_FILE.exists():
        return counts
    try:
        with USAGE_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                tools = obj.get("tools")
                if not isinstance(tools, list):
                    continue
                for t in tools:
                    if isinstance(t, str):
                        counts[t] = counts.get(t, 0) + 1
                    elif isinstance(t, dict):
                        name = t.get("name") or t.get("skill") or t.get("tool")
                        if isinstance(name, str):
                            counts[name] = counts.get(name, 0) + 1
    except OSError:
        pass
    return counts


def _load_skills() -> list[dict[str, Any]]:
    skills: list[dict[str, Any]] = []
    if not SKILLS_ROOT.exists():
        return skills

    usage_counts = _usage_counts_by_skill()

    for skill_md in sorted(SKILLS_ROOT.rglob("SKILL.md")):
        try:
            text = skill_md.read_text(encoding="utf-8")
        except OSError:
            continue
        fm, _body = _parse_frontmatter(text)
        skill_dir = skill_md.parent

        name = str(fm.get("name") or skill_dir.name)
        description = str(fm.get("description") or "").strip()

        rel_parent = skill_dir.relative_to(SKILLS_ROOT).parent
        if rel_parent.parts:
            category = rel_parent.parts[0]
        else:
            tags = fm.get("tags") or fm.get("category") or fm.get("categories")
            if isinstance(tags, list) and tags:
                category = str(tags[0])
            elif isinstance(tags, str) and tags:
                category = tags.split(",")[0].strip()
            else:
                category = "uncategorized"

        skills.append(
            {
                "name": name,
                "description": description[:500],
                "category": category,
                "size": len(text),
                "usage_count": int(usage_counts.get(name, 0)),
            }
        )
    return skills


def _load_journal_entries(n: int = 5) -> list[dict[str, str]]:
    if not JOURNAL_FILE.exists():
        return []
    try:
        text = JOURNAL_FILE.read_text(encoding="utf-8")
    except OSError:
        return []

    chunks = re.split(r"(?m)^(?:#{1,3}\s+|---\s*$)", text)
    entries: list[dict[str, str]] = []
    for raw in chunks:
        raw = raw.strip()
        if len(raw) < 8:
            continue
        first, _, rest = raw.partition("\n")
        entries.append(
            {
                "title": first.strip("# ").strip()[:140],
                "body": rest.strip()[:600],
            }
        )
    # Append-only journals put the newest entry last.
    return list(reversed(entries))[:n]


def _load_usage(n: int = 30) -> list[dict[str, Any]]:
    if not USAGE_FILE.exists():
        return []
    rows: list[dict[str, Any]] = []
    try:
        with USAGE_FILE.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
    except OSError:
        return []
    return rows[-n:]


# ---------------------------------------------------------------------------
# handlers
# ---------------------------------------------------------------------------


async def _index(request: web.Request) -> web.Response:
    return web.Response(text=INDEX_HTML, content_type="text/html")


async def _api_skills(request: web.Request) -> web.Response:
    data = await asyncio.to_thread(_load_skills)
    return web.json_response(data)


async def _api_journal(request: web.Request) -> web.Response:
    data = await asyncio.to_thread(_load_journal_entries, 5)
    return web.json_response(data)


async def _api_usage(request: web.Request) -> web.Response:
    data = await asyncio.to_thread(_load_usage, 30)
    return web.json_response(data)


# ---------------------------------------------------------------------------
# app factory + entrypoint
# ---------------------------------------------------------------------------


def make_app() -> web.Application:
    app = web.Application()
    app.add_routes(
        [
            web.get("/", _index),
            web.get("/api/skills", _api_skills),
            web.get("/api/journal", _api_journal),
            web.get("/api/usage", _api_usage),
        ]
    )
    return app


async def start(port: int = 8765) -> web.AppRunner:
    """Start the dashboard server bound to 127.0.0.1.

    Returns the live :class:`aiohttp.web.AppRunner` so the caller can
    ``await runner.cleanup()`` on shutdown.
    """
    app = make_app()
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, host="127.0.0.1", port=port)
    await site.start()
    return runner


# ---------------------------------------------------------------------------
# inline HTML
# ---------------------------------------------------------------------------

INDEX_HTML = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width,initial-scale=1" />
<title>OpenGriffin · Skill Graph</title>
<script src="https://d3js.org/d3.v7.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&family=JetBrains+Mono:wght@400;500&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #000;
    --bg-2: #0a0a0d;
    --line: #1a1a20;
    --ink: #f5f5f7;
    --muted: #8a8a93;
    --electric: #22d3ee;
    --violet: #8b5cf6;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; height: 100%; background: var(--bg); color: var(--ink); }
  body { font-family: 'Inter', system-ui, sans-serif; -webkit-font-smoothing: antialiased; overflow: hidden; }
  a { color: var(--electric); text-decoration: none; }
  a:hover { text-decoration: underline; }

  #app { display: grid; grid-template-columns: 320px 1fr; height: 100vh; }
  aside {
    background: var(--bg-2); border-right: 1px solid var(--line);
    overflow-y: auto; padding: 24px 22px;
  }
  aside h1 {
    font-size: 16px; font-weight: 700; letter-spacing: -.01em;
    margin: 0 0 4px; display: flex; align-items: center; gap: 8px;
  }
  aside h1::before {
    content: ""; width: 8px; height: 8px; border-radius: 50%;
    background: var(--electric); box-shadow: 0 0 12px var(--electric);
  }
  aside .sub { color: var(--muted); font-size: 12px; margin-bottom: 28px; letter-spacing: .04em; }

  aside h2 {
    font-size: 11px; font-weight: 600; text-transform: uppercase;
    letter-spacing: .18em; color: var(--muted); margin: 24px 0 12px;
  }
  .journal article {
    border-left: 2px solid var(--line); padding: 4px 0 10px 12px; margin-bottom: 12px;
  }
  .journal article:hover { border-left-color: var(--electric); }
  .journal h3 { font-size: 13px; font-weight: 600; margin: 0 0 4px; color: var(--ink); }
  .journal p  { font-size: 12px; color: var(--muted); margin: 0; line-height: 1.45;
                display: -webkit-box; -webkit-line-clamp: 3; -webkit-box-orient: vertical; overflow: hidden; }

  .usage-card {
    background: rgba(34, 211, 238, .04);
    border: 1px solid rgba(34, 211, 238, .15);
    border-radius: 8px; padding: 12px;
  }
  .usage-card .meta { display: flex; justify-content: space-between; font-size: 11px; color: var(--muted); margin-bottom: 6px; letter-spacing: .04em; }
  .usage-card svg { display: block; }

  main { position: relative; overflow: hidden; }
  main .legend {
    position: absolute; top: 18px; right: 18px; z-index: 5;
    background: rgba(10,10,13,.7); backdrop-filter: blur(8px);
    border: 1px solid var(--line); border-radius: 8px; padding: 12px 14px;
    font-size: 11px; max-width: 260px; max-height: 60vh; overflow-y: auto;
  }
  .legend h3 { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .18em; color: var(--muted); margin: 0 0 8px; }
  .legend .row { display: flex; align-items: center; gap: 8px; padding: 3px 0; cursor: pointer; }
  .legend .row:hover { color: var(--electric); }
  .legend .swatch { width: 10px; height: 10px; border-radius: 50%; flex-shrink: 0; }
  .legend .count { color: var(--muted); margin-left: auto; font-family: 'JetBrains Mono', monospace; font-size: 10px; }

  main .stats {
    position: absolute; bottom: 18px; left: 18px; z-index: 5;
    font-family: 'JetBrains Mono', monospace; font-size: 11px; color: var(--muted);
  }
  main .stats span { color: var(--electric); }

  svg.graph { width: 100%; height: 100%; display: block; cursor: grab; }
  svg.graph:active { cursor: grabbing; }
  .link { stroke: var(--electric); stroke-opacity: .15; }
  .node circle { transition: stroke-width .15s, filter .15s; }
  .node:hover circle { stroke: #fff; stroke-width: 1.5; filter: drop-shadow(0 0 6px var(--electric)); }
  .node text { font-family: 'JetBrains Mono', monospace; font-size: 9px; fill: var(--muted); pointer-events: none; }
  .node.cat text { font-size: 11px; font-weight: 600; fill: var(--ink); }

  #tooltip {
    position: fixed; z-index: 100; pointer-events: none;
    background: rgba(0,0,0,.92); border: 1px solid var(--electric);
    border-radius: 6px; padding: 10px 12px; max-width: 320px;
    font-size: 12px; line-height: 1.45; color: var(--ink);
    box-shadow: 0 4px 24px rgba(0,0,0,.5), 0 0 16px rgba(34,211,238,.2);
    display: none;
  }
  #tooltip strong { display: block; font-size: 13px; margin-bottom: 4px; }
  #tooltip .cat { color: var(--electric); font-family: 'JetBrains Mono', monospace; font-size: 10px; letter-spacing: .04em; margin-bottom: 6px; }
  #tooltip .desc { color: var(--muted); }

  .empty { color: var(--muted); font-size: 12px; padding: 8px 0; font-style: italic; }
</style>
</head>
<body>
<div id="app">
  <aside>
    <h1>OpenGriffin</h1>
    <div class="sub">SKILL GRAPH · LOCAL DASHBOARD</div>

    <h2>Recent journal</h2>
    <div class="journal" id="journal"><div class="empty">Loading…</div></div>

    <h2>Usage · last 30</h2>
    <div class="usage-card">
      <div class="meta"><span>tokens</span><span id="usageTotal">—</span></div>
      <svg id="usageSpark" width="276" height="48"></svg>
    </div>
  </aside>

  <main>
    <div class="legend" id="legend"></div>
    <div class="stats" id="stats"></div>
    <svg class="graph" id="graph"></svg>
  </main>
</div>

<div id="tooltip"></div>

<script>
const palette = [
  '#22d3ee', '#8b5cf6', '#f472b6', '#fbbf24', '#34d399',
  '#60a5fa', '#f87171', '#a78bfa', '#2dd4bf', '#fb923c',
  '#e879f9', '#84cc16', '#facc15', '#4ade80', '#06b6d4',
];

const escapeHTML = (s) => String(s ?? '').replace(/[&<>"']/g, c => (
  {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]
));

(async function init() {
  const [skills, journal, usage] = await Promise.all([
    fetch('/api/skills').then(r => r.json()).catch(() => []),
    fetch('/api/journal').then(r => r.json()).catch(() => []),
    fetch('/api/usage').then(r => r.json()).catch(() => []),
  ]);
  renderJournal(journal);
  renderUsage(usage);
  renderGraph(skills);
})();

function renderJournal(entries) {
  const root = document.getElementById('journal');
  if (!entries || !entries.length) {
    root.innerHTML = '<div class="empty">No journal entries yet.</div>';
    return;
  }
  root.innerHTML = entries.map(e =>
    `<article><h3>${escapeHTML(e.title)}</h3><p>${escapeHTML(e.body)}</p></article>`
  ).join('');
}

function renderUsage(rows) {
  const svg = d3.select('#usageSpark');
  const w = 276, h = 48;
  svg.selectAll('*').remove();
  if (!rows || !rows.length) {
    document.getElementById('usageTotal').textContent = '0';
    svg.append('text').attr('x', w/2).attr('y', h/2)
      .attr('text-anchor', 'middle').attr('fill', '#444')
      .attr('font-size', 10).text('no usage data');
    return;
  }
  const values = rows.map(r => +(
    r.tokens ?? r.total_tokens ??
    ((+r.input_tokens || 0) + (+r.output_tokens || 0)) ?? 0
  )) || [];
  const total = values.reduce((a,b) => a+b, 0);
  document.getElementById('usageTotal').textContent = total.toLocaleString();

  const x = d3.scaleLinear().domain([0, Math.max(1, values.length - 1)]).range([2, w - 2]);
  const y = d3.scaleLinear().domain([0, d3.max(values) || 1]).range([h - 4, 4]);
  const area = d3.area().x((_, i) => x(i)).y0(h - 4).y1(d => y(d)).curve(d3.curveMonotoneX);
  const line = d3.line().x((_, i) => x(i)).y(d => y(d)).curve(d3.curveMonotoneX);

  const grad = svg.append('defs').append('linearGradient')
    .attr('id', 'sparkGrad').attr('x1', 0).attr('x2', 0).attr('y1', 0).attr('y2', 1);
  grad.append('stop').attr('offset', '0%').attr('stop-color', '#22d3ee').attr('stop-opacity', .5);
  grad.append('stop').attr('offset', '100%').attr('stop-color', '#22d3ee').attr('stop-opacity', 0);

  svg.append('path').attr('d', area(values)).attr('fill', 'url(#sparkGrad)');
  svg.append('path').attr('d', line(values))
    .attr('fill', 'none').attr('stroke', '#22d3ee').attr('stroke-width', 1.4);
}

function renderGraph(skills) {
  const svg = d3.select('#graph');
  const main = document.querySelector('main');
  const w = main.clientWidth;
  const h = main.clientHeight;
  svg.attr('viewBox', `0 0 ${w} ${h}`);

  if (!skills.length) {
    svg.append('text').attr('x', w/2).attr('y', h/2)
      .attr('text-anchor', 'middle').attr('fill', '#666')
      .attr('font-size', 14).text('No skills found at ~/.claude/skills/');
    document.getElementById('stats').innerHTML = '<span>0</span> skills';
    return;
  }

  const cats = Array.from(new Set(skills.map(s => s.category))).sort();
  const color = d3.scaleOrdinal().domain(cats).range(palette);

  const catCounts = cats.map(c => ({
    name: c, count: skills.filter(s => s.category === c).length,
  }));

  const nodes = [
    ...cats.map(c => ({ id: 'cat:' + c, name: c, isCategory: true })),
    ...skills.map(s => ({ ...s, id: 'skill:' + s.name })),
  ];
  const links = skills.map(s => ({
    source: 'skill:' + s.name, target: 'cat:' + s.category,
  }));

  const maxSize = d3.max(skills, s => s.size) || 1;
  const sizeScale = d3.scaleSqrt().domain([0, maxSize]).range([4, 22]);

  const sim = d3.forceSimulation(nodes)
    .force('link', d3.forceLink(links).id(d => d.id).distance(70).strength(.4))
    .force('charge', d3.forceManyBody().strength(d => d.isCategory ? -380 : -70))
    .force('center', d3.forceCenter(w / 2, h / 2))
    .force('collide', d3.forceCollide().radius(d => d.isCategory ? 32 : sizeScale(d.size) + 3));

  const linkSel = svg.append('g').attr('class', 'links')
    .selectAll('line').data(links).join('line').attr('class', 'link');

  const nodeSel = svg.append('g').attr('class', 'nodes')
    .selectAll('g').data(nodes).join('g')
    .attr('class', d => 'node' + (d.isCategory ? ' cat' : ''))
    .call(d3.drag()
      .on('start', (e, d) => { if (!e.active) sim.alphaTarget(.3).restart(); d.fx = d.x; d.fy = d.y; })
      .on('drag',  (e, d) => { d.fx = e.x; d.fy = e.y; })
      .on('end',   (e, d) => { if (!e.active) sim.alphaTarget(0); d.fx = null; d.fy = null; }));

  nodeSel.append('circle')
    .attr('r', d => d.isCategory ? 14 : sizeScale(d.size))
    .attr('fill', d => d.isCategory ? '#000' : color(d.category))
    .attr('fill-opacity', d => d.isCategory ? 1 : .85)
    .attr('stroke', d => d.isCategory ? color(d.name) : 'rgba(255,255,255,.1)')
    .attr('stroke-width', d => d.isCategory ? 2 : .5);

  nodeSel.filter(d => d.isCategory).append('text')
    .text(d => d.name).attr('text-anchor', 'middle').attr('dy', 28);

  nodeSel.filter(d => !d.isCategory)
    .on('mouseover', (e, d) => showTooltip(e, d))
    .on('mousemove', (e) => moveTooltip(e))
    .on('mouseout', hideTooltip);

  sim.on('tick', () => {
    linkSel
      .attr('x1', d => d.source.x).attr('y1', d => d.source.y)
      .attr('x2', d => d.target.x).attr('y2', d => d.target.y);
    nodeSel.attr('transform', d => `translate(${d.x},${d.y})`);
  });

  // legend
  const legend = document.getElementById('legend');
  legend.innerHTML = '<h3>Categories · ' + cats.length + '</h3>' + catCounts.map(c =>
    `<div class="row" data-cat="${escapeHTML(c.name)}">
       <span class="swatch" style="background:${color(c.name)}"></span>
       <span>${escapeHTML(c.name)}</span>
       <span class="count">${c.count}</span>
     </div>`
  ).join('');
  legend.querySelectorAll('.row').forEach(row => {
    row.addEventListener('mouseenter', () => {
      const cat = row.dataset.cat;
      nodeSel.attr('opacity', d => d.isCategory ? (d.name === cat ? 1 : .15) : (d.category === cat ? 1 : .15));
      linkSel.attr('opacity', d => (d.target.name === cat || d.source.category === cat) ? .6 : .04);
    });
    row.addEventListener('mouseleave', () => {
      nodeSel.attr('opacity', 1);
      linkSel.attr('opacity', null);
    });
  });

  document.getElementById('stats').innerHTML =
    `<span>${skills.length}</span> skills · <span>${cats.length}</span> categories · ` +
    `<span>${(skills.reduce((a,s) => a + s.size, 0) / 1024).toFixed(1)}k</span> chars`;

  // zoom + pan
  svg.call(d3.zoom().scaleExtent([.3, 3]).on('zoom', (e) => {
    svg.selectAll('g.links, g.nodes').attr('transform', e.transform);
  }));
}

function showTooltip(e, d) {
  const t = document.getElementById('tooltip');
  t.innerHTML =
    `<strong>${escapeHTML(d.name)}</strong>` +
    `<div class="cat">${escapeHTML(d.category)} · ${d.size.toLocaleString()} chars · ${d.usage_count}× used</div>` +
    `<div class="desc">${escapeHTML(d.description) || '<em>No description.</em>'}</div>`;
  t.style.display = 'block';
  moveTooltip(e);
}
function moveTooltip(e) {
  const t = document.getElementById('tooltip');
  const pad = 14;
  let x = e.clientX + pad, y = e.clientY + pad;
  if (x + t.offsetWidth > window.innerWidth) x = e.clientX - t.offsetWidth - pad;
  if (y + t.offsetHeight > window.innerHeight) y = e.clientY - t.offsetHeight - pad;
  t.style.left = x + 'px'; t.style.top = y + 'px';
}
function hideTooltip() { document.getElementById('tooltip').style.display = 'none'; }
</script>
</body>
</html>
"""


if __name__ == "__main__":

    async def _main() -> None:
        port = 8765
        runner = await start(port)
        print(f"OpenGriffin dashboard at http://127.0.0.1:{port}")
        try:
            await asyncio.Event().wait()
        finally:
            await runner.cleanup()

    asyncio.run(_main())
