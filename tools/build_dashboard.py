#!/usr/bin/env python3
"""Generates dashboard/index.html with the Rommbic brand system and the logo
embedded as a data URI. Run once (or after changing the logo)."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
DASH = HERE.parent / "dashboard"
import base64
LOGO_SRC = HERE.parent / "assets" / "logo.png"
logo_b64 = base64.b64encode(LOGO_SRC.read_bytes()).decode()
LOGO = f"data:image/png;base64,{logo_b64}"

HTML = r"""<!doctype html>
<html lang="en-GB">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="robots" content="noindex, nofollow">
<title>Rommbic Intelligence Portal</title>
<link rel="icon" href="__LOGO__">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Anton&family=IBM+Plex+Sans:ital,wght@0,400;0,500;0,600;0,700;1,400&display=swap" rel="stylesheet">
<style>
  :root{
    --paper:#fdfbf8;      /* Blueprint White  */
    --ink:#161614;        /* Near Black       */
    --slate:#2e4a54;      /* Safety Slate     */
    --amber:#e87511;      /* High-Vis Amber   */
    --tint:#fef2e5;       /* Amber Tint       */
    --line:#e7e1d6;
    --muted:rgba(46,74,84,.55);
    --display:'Anton',Impact,sans-serif;
    --body:'IBM Plex Sans',system-ui,-apple-system,sans-serif;
  }
  *{box-sizing:border-box}
  html,body{margin:0}
  body{background:var(--paper);color:var(--ink);font-family:var(--body);
    font-size:16px;line-height:1.4;letter-spacing:-.01em;-webkit-font-smoothing:antialiased}
  .wrap{max-width:960px;margin:0 auto;padding:0 22px}
  a{color:inherit}

  /* ---------- Masthead (near-black band) ---------- */
  .masthead{background:var(--ink);border-bottom:3px solid var(--amber)}
  .mast-in{max-width:960px;margin:0 auto;padding:18px 22px;display:flex;
    align-items:center;gap:16px;flex-wrap:wrap}
  .logo{width:46px;height:46px;border-radius:9px;display:block;flex:0 0 auto}
  .brand{display:flex;flex-direction:column;gap:2px}
  .brand .kick{font-size:10px;letter-spacing:.22em;text-transform:uppercase;
    color:rgba(253,251,248,.5);font-weight:600}
  .brand .name{display:flex;align-items:baseline;gap:10px}
  .brand .name b{font-family:var(--display);font-weight:400;font-size:27px;
    letter-spacing:.01em;color:var(--paper);line-height:1}
  .brand .name span{font-size:12px;font-weight:600;letter-spacing:.18em;
    text-transform:uppercase;color:var(--paper)}
  .brand .name span::before{content:"";display:inline-block;width:2px;height:13px;
    background:var(--amber);margin-right:10px;vertical-align:-1px}
  .mast-meta{margin-left:auto;text-align:right;font-size:11px;letter-spacing:.08em;
    text-transform:uppercase;color:rgba(253,251,248,.55);line-height:1.7}
  .mast-meta b{color:var(--amber);font-family:var(--display);font-weight:400;
    font-size:18px;letter-spacing:.02em}
  .mast-meta select{font-family:var(--body);font-size:11px;background:transparent;
    border:1px solid rgba(253,251,248,.25);border-radius:5px;padding:3px 7px;
    color:var(--paper);letter-spacing:.06em}

  /* ---------- Section title ---------- */
  .lede{display:flex;align-items:flex-end;justify-content:space-between;
    gap:16px;padding:26px 0 8px;flex-wrap:wrap}
  .lede h1{font-family:var(--display);font-weight:400;font-size:clamp(30px,5.5vw,46px);
    letter-spacing:-.01em;line-height:.95;margin:0;text-transform:uppercase}
  .lede h1 i{font-style:normal;color:var(--amber)}
  .lede p{margin:0;font-size:13px;color:var(--slate)}

  /* ---------- Controls ---------- */
  .controls{position:sticky;top:0;z-index:5;background:var(--paper);
    border-top:1px solid var(--line);border-bottom:1px solid var(--line);
    padding:13px 0;margin:10px 0 4px;display:flex;flex-wrap:wrap;gap:11px;align-items:center}
  .chips{display:flex;flex-wrap:wrap;gap:6px}
  .chip{font-size:11px;letter-spacing:.04em;text-transform:uppercase;font-weight:600;
    border:1px solid var(--line);background:#fff;padding:5px 11px;border-radius:30px;
    cursor:pointer;color:var(--slate);transition:.15s;white-space:nowrap}
  .chip:hover{border-color:var(--slate)}
  .chip.on{background:var(--ink);color:var(--paper);border-color:var(--ink)}
  .spacer{flex:1 1 12px}
  .slider{display:flex;align-items:center;gap:8px;font-size:10px;color:var(--muted);
    text-transform:uppercase;letter-spacing:.08em;font-weight:600}
  .slider b{color:var(--ink);font-family:var(--display);font-weight:400;font-size:15px}
  input[type=range]{accent-color:var(--amber);width:96px}
  input[type=search]{font-family:var(--body);font-size:13px;border:1px solid var(--line);
    border-radius:7px;padding:7px 11px;background:#fff;min-width:170px;color:var(--ink)}
  input[type=search]:focus{outline:none;border-color:var(--amber)}

  /* ---------- Items ---------- */
  .item{display:grid;grid-template-columns:62px 1fr;gap:18px;padding:20px 0;
    border-bottom:1px solid var(--line);animation:rise .45s both}
  .item.hot{background:var(--tint);border-left:3px solid var(--amber);
    padding-left:14px;margin-left:-17px;border-bottom-color:#f0e3cf}
  .item:nth-child(1){animation-delay:.02s}.item:nth-child(2){animation-delay:.05s}
  .item:nth-child(3){animation-delay:.08s}.item:nth-child(4){animation-delay:.11s}
  .item:nth-child(5){animation-delay:.14s}
  @keyframes rise{from{opacity:0;transform:translateY(7px)}to{opacity:1;transform:none}}
  .score{font-family:var(--display);font-weight:400;font-size:34px;line-height:.9;
    text-align:center;padding-top:3px}
  .score small{display:block;font-family:var(--body);font-size:8px;font-weight:600;
    letter-spacing:.16em;color:var(--muted);margin-top:6px}
  .s-high{color:var(--amber)} .s-med{color:var(--slate)} .s-low{color:var(--muted)}
  .item h2{font-size:17px;font-weight:600;line-height:1.25;margin:0 0 7px;color:var(--ink)}
  .item h2 a{text-decoration:none;background:linear-gradient(var(--amber),var(--amber)) 0 100%/0% 2px no-repeat;transition:background-size .25s}
  .item h2 a:hover{background-size:100% 2px}
  .meta{display:flex;flex-wrap:wrap;gap:6px;align-items:center;margin-bottom:6px;
    font-size:10px;letter-spacing:.06em;text-transform:uppercase;font-weight:600}
  .tag{border:1px solid var(--line);color:var(--slate);border-radius:4px;padding:2px 7px;white-space:nowrap}
  .tag.co{border-color:var(--amber);color:var(--amber)}
  .src{color:var(--muted)}
  .why{font-size:14px;color:var(--slate);font-style:italic;letter-spacing:-.005em}
  .roles{font-size:10px;letter-spacing:.06em;text-transform:uppercase;color:var(--muted);
    font-weight:600;margin-top:5px}

  .empty{padding:70px 0;text-align:center;color:var(--muted);font-style:italic}
  footer{border-top:1px solid var(--line);margin-top:36px;padding:22px 0 60px;
    font-size:11px;color:var(--muted);display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}
  footer b{font-family:var(--display);font-weight:400;color:var(--ink);letter-spacing:.02em;font-size:13px}
  footer b i{font-style:normal;color:var(--amber)}
  @media(max-width:560px){.item{grid-template-columns:46px 1fr;gap:12px}.score{font-size:26px}}
</style>
</head>
<body>
  <div class="masthead">
    <div class="mast-in">
      <img class="logo" src="__LOGO__" alt="Rommbic">
      <div class="brand">
        <div class="kick">Construction Products Recruitment Intelligence</div>
        <div class="name"><b>ROMMBIC</b><span>Intelligence Portal</span></div>
      </div>
      <div class="mast-meta">
        <div id="dateline">Loading…</div>
        <div><b id="count">0</b> signals &nbsp;·&nbsp; <b id="shown">0</b> shown
          &nbsp;·&nbsp; Archive <select id="history"></select></div>
      </div>
    </div>
  </div>

  <div class="wrap">
    <div class="lede">
      <h1>Live Signal <i>Brief</i></h1>
      <p>Hiring-intent signals across your target market — refreshed through the day.</p>
    </div>

    <div class="controls">
      <div class="chips" id="chips"></div>
      <span class="spacer"></span>
      <label class="slider">Min&nbsp;score <input type="range" id="minScore" min="1" max="10" value="1"><b id="minScoreVal">1</b></label>
      <input type="search" id="q" placeholder="search headlines or company…">
    </div>

    <div id="list"></div>

    <footer>
      <span>Generated automatically · scores 1–10 indicate hiring-intent strength.</span>
      <b>Serious searching<i>.</i> No time wasted<i>.</i></b>
    </footer>
  </div>

<script>
const state={items:[],cats:new Set(),active:new Set(),min:1,q:""};
const band=s=>s>=8?"s-high":s>=6?"s-med":"s-low";
const esc=t=>{const d=document.createElement("div");d.textContent=t||"";return d.innerHTML;};

async function loadDay(file){
  try{
    const r=await fetch(file,{cache:"no-store"});if(!r.ok)throw 0;
    const data=await r.json();
    state.items=data.items||[];state.cats=new Set(data.categories||[]);
    document.getElementById("dateline").textContent=
      new Date(data.generated_at).toLocaleString("en-GB",{weekday:"short",day:"numeric",month:"short",hour:"2-digit",minute:"2-digit"});
    document.getElementById("count").textContent=state.items.length;
    buildChips();render();
  }catch(e){
    document.getElementById("dateline").textContent="No brief yet";
    document.getElementById("list").innerHTML='<div class="empty">The first brief appears after the agent runs.</div>';
  }
}
function buildChips(){
  const c=document.getElementById("chips");c.innerHTML="";
  [...state.cats].forEach(cat=>{
    const el=document.createElement("span");
    el.className="chip"+(state.active.has(cat)?" on":"");el.textContent=cat;
    el.onclick=()=>{state.active.has(cat)?state.active.delete(cat):state.active.add(cat);buildChips();render();};
    c.appendChild(el);
  });
}
function render(){
  let rows=state.items.filter(it=>{
    if(it.score<state.min)return false;
    if(state.active.size&&!it.categories.some(x=>state.active.has(x)))return false;
    if(state.q&&!((it.title+" "+(it.company||"")).toLowerCase().includes(state.q)))return false;
    return true;
  });
  document.getElementById("shown").textContent=rows.length;
  const list=document.getElementById("list");
  if(!rows.length){list.innerHTML='<div class="empty">No signals match these filters.</div>';return;}
  list.innerHTML=rows.map(it=>`
    <div class="item${it.score>=9?' hot':''}">
      <div class="score ${band(it.score)}">${it.score}<small>SCORE</small></div>
      <div>
        <h2><a href="${esc(it.link)}" target="_blank" rel="noopener">${esc(it.title)}</a></h2>
        <div class="meta">
          ${it.company?`<span class="tag co">${esc(it.company)}</span>`:""}
          ${(it.categories||[]).map(c=>`<span class="tag">${esc(c)}</span>`).join("")}
          ${it.source?`<span class="src">${esc(it.source)}</span>`:""}
        </div>
        ${it.rationale?`<div class="why">${esc(it.rationale)}</div>`:""}
        ${it.likely_roles?`<div class="roles">Roles → ${esc(it.likely_roles)}</div>`:""}
      </div>
    </div>`).join("");
}
document.getElementById("minScore").oninput=e=>{state.min=+e.target.value;document.getElementById("minScoreVal").textContent=state.min;render();};
document.getElementById("q").oninput=e=>{state.q=e.target.value.toLowerCase().trim();render();};
document.getElementById("history").onchange=e=>loadDay(e.target.value==="latest"?"./data/latest.json":`./data/${e.target.value}.json`);
(async function(){
  const sel=document.getElementById("history");sel.innerHTML='<option value="latest">Today</option>';
  try{const idx=await(await fetch("./data/index.json",{cache:"no-store"})).json();
    (idx.dates||[]).forEach(d=>{const o=document.createElement("option");o.value=d;o.textContent=d;sel.appendChild(o);});}catch(e){}
  loadDay("./data/latest.json");
})();
</script>
</body>
</html>
"""

out = HTML.replace("__LOGO__", LOGO)
(DASH / "index.html").write_text(out, encoding="utf-8")
print("dashboard/index.html rebuilt with brand system; size", len(out), "bytes")
