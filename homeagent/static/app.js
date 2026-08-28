"use strict";
const $ = id => document.getElementById(id);
const feed = $("feed"), inner = $("inner"), input = $("input"),
      modelSel = $("model"), prevRow = $("prevRow"), fileIn = $("file");
let chats = [], current = null, modelDefault = "", pendingImages = [],
    busy = false, controller = null;

/* ---------------- utils ---------------- */
const esc = s => s.replace(/[&<>"']/g, c => ({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]));
const now = () => new Date().toLocaleTimeString([], {hour:"2-digit", minute:"2-digit"});
const atBottom = () => feed.scrollHeight - feed.scrollTop - feed.clientHeight < 90;

function inline(s){
  s = s.replace(/`([^`\n]+)`/g, (m,c)=>"\u0001I"+c+"\u0001");
  s = s.replace(/\*\*([^*]+)\*\*/g, "<b>$1</b>");
  s = s.replace(/(^|[\s(])\*([^*\n]+)\*/g, "$1<i>$2</i>");
  s = s.replace(/\[([^\]]+)\]\((https?:[^)\s]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  s = s.replace(/\u0001I([^\u0001]*)\u0001/g, "<code>$1</code>");
  return s;
}
function asciiTables(s){
  // turn fenced "tables" of +- | chars into real html tables
  const rows = s.split("\n").map(r => r.trim()).filter(r => r.length);
  const isBorder = r => /^[\s|+\-=_]+$/.test(r) && (r.includes("-") || r.includes("="));
  if (!rows.length || !rows.some(isBorder) || !rows.some(r=>r.includes("|"))) return s;
  const body = rows.filter(r=>!isBorder(r));
  if (!body.length) return s;
  const split = r => r.replace(/^\s*\|/,"").replace(/\|\s*$/,"").split("|").map(c=>c.trim());
  let maxc = Math.max(...body.map(r=>split(r).length));
  if (maxc < 2 || !rows.every(r=>isBorder(r)||split(r).length===maxc)) return s;
  const head = split(body[0]);
  let html = "<table><thead><tr>" + head.map(h=>"<th>"+esc(h)+"</th>").join("") + "</tr></thead><tbody>";
  for (const r of body.slice(1)) html += "<tr>"+split(r).map(c=>"<td>"+esc(c)+"</td>").join("")+"</tr>";
  return html + "</tbody></table>";
}
function renderMarkdown(raw){
  let s = esc(raw);
  // 1) extract fenced code blocks so inner rules don't touch them
  const blocks = [];
  s = s.replace(/```([\w+#-]*)\n?([\s\S]*?)```/g, (m,lang,code)=>{
    blocks.push({code: code.replace(/\n$/,"")});
    return "\u0002B"+(blocks.length-1)+"\u0002";
  });
  // 2) headers
  s = s.replace(/^###\s+(.*)$/gm, "<h3>$1</h3>")
       .replace(/^##\s+(.*)$/gm, "<h2>$1</h2>")
       .replace(/^#\s+(.*)$/gm, "<h1>$1</h1>");
  // 3) unordered / ordered lists
  s = s.replace(/((?:^\s*[-*]\s+[^\n]+\n?)+)/gm, m =>
      "<ul>" + m.trim().split("\n").map(l=>"<li>"+inline(l.replace(/^\s*[-*]\s+/,""))+"</li>").join("") + "</ul>");
  s = s.replace(/((?:^\s*\d+\.\s+[^\n]+\n?)+)/gm, m =>
      "<ol>" + m.trim().split("\n").map(l=>"<li>"+inline(l.replace(/^\s*\d+\.\s+/,""))+"</li>").join("") + "</ol>");
  // 4) paragraphs (keep already-tagged chunks as-is)
  s = s.split(/\n{2,}/).map(chunk => {
    const t = chunk.trim();
    if (!t) return "";
    if (/^<(h\d|ul|ol|pre|table|code|blockquote|img)/.test(t)) return t;
    return "<p>" + t.replace(/\n/g,"<br>") + "</p>";
  }).join("\n");
  // 5) ascii tables: if a paragraph is a boxed ascii table, upgrade it
  s = s.replace(/<p>([\s\S]*?)<\/p>/g, (m, body) => {
    const plain = body.replace(/<br>/g,"\n").replace(/<[^>]+>/g,"");
    const upgraded = asciiTables(plain);
    return /^<table>/.test(upgraded) ? upgraded : m;
  });
  // 6) restore code blocks
  s = s.replace(/\u0002B(\d+)\u0002/g, (m,i)=>
      "<pre><button class='copy'>copy</button><code>" + esc(blocks[+i].code) + "</code></pre>");
  return s;
}

/* ---------------- rendering ---------------- */
function msgNode(role, content, opts={}){
  const el = document.createElement("div");
  el.className = "msg " + role;
  const avatar = role === "user" ? "You" : "🏠";
  const imgs = (opts.images||[]).map(u =>
    `<img src="${u}" alt="attachment" style="max-width:220px;border-radius:8px;margin-top:6px;display:block">`).join("");
  el.innerHTML = `
    <div class="avatar">${avatar}</div>
    <div class="bubble">
      <div class="meta"><span>${role==="user"?"You":"Home Agent"}${opts.model?` · ${esc(opts.model)}`:""}${opts.ms?` · ${(opts.ms/1000).toFixed(1)}s`:""}</span><span class="t">${esc(now())}</span></div>
      <div class="content">${role==="user" ? esc(content) + imgs : ""}</div>
    </div>`;
  return el;
}
function addMessage(role, content, opts={}){
  const stick = atBottom();
  const node = msgNode(role, content, opts);
  inner.appendChild(node);
  if (stick) feed.scrollTop = feed.scrollHeight;
  return node;
}
function emptyState(){
  if (inner.children.length) return;
  const d = document.createElement("div");
  d.className = "empty"; d.id = "empty";
  d.innerHTML = `<div class="big">🏠</div>
    <b style="color:var(--text)">Home Agent</b>
    <span>Local chat with your Ollama models — <b style="color:var(--text)">${esc(modelDefault||"qwen3.8:27b")}</b> by default.</span>
    <span>Try asking it to write a Python script, explain an error, or <i>attach a screenshot</i>.</span>
    <span><kbd>Enter</kbd> send · <kbd>Shift</kbd>+<kbd>Enter</kbd> newline · <kbd>🖼</kbd> image</span>`;
  feed.prepend(d);
}
function clearEmpty(){ const e = $("empty"); if (e) e.remove(); }

/* ---------------- sidebar ---------------- */
function renderChats(){
  const list = $("chatList"); list.innerHTML = "";
  chats.forEach(c => {
    const chip = document.createElement("div");
    chip.className = "chip" + (current && current.id === c.id ? " active" : "");
    chip.innerHTML = `<span class="t">${esc(c.title)}</span><span class="n">${c.n||0}</span><button class="x" title="Delete">✕</button>`;
    chip.onclick = e => { if (e.target.classList.contains("x")) return deleteChat(c.id); openChat(c.id); };
    list.appendChild(chip);
  });
  if (!chats.length) list.innerHTML = `<div style="padding:10px 12px;font-size:12px;color:var(--dim)">No chats yet</div>`;
}
async function loadChats(){
  const r = await fetch("/api/chats").then(x=>x.json());
  chats = r.chats; modelDefault = r.default_model;
  renderChats();
}
async function deleteChat(id){
  if (!confirm("Delete this chat and its messages?")) return;
  await fetch("/api/chats/"+id, {method:"DELETE"});
  if (current && current.id === id) current = null;
  await loadChats();
  if (!current) newChatLocal();
}
async function newChat(){
  await newChatLocal();
  input.focus();
}
async function newChatLocal(){
  const r = await fetch("/api/chats", {method:"POST", headers:{"Content-Type":"application/json"},
    body: JSON.stringify({model: modelSel.value})}).then(x=>x.json());
  current = r.chat;
  await loadChats();
  inner.innerHTML = ""; emptyState();
  $("chatTitle").textContent = "New chat";
}
async function openChat(id){
  const r = await fetch("/api/chats/"+id).then(x=>x.json());
  current = r.chat;
  modelSel.value = r.chat.model;
  inner.innerHTML = "";
  r.messages.forEach(m => {
    if (m.role === "user") addMessage("user", m.content, {images: JSON.parse(m.images||"[]")});
    else addMessage("assistant", m.content, {model:m.model, ms:m.response_ms});
  });
  if (!r.messages.length) emptyState();
  $("chatTitle").textContent = r.chat.title;
  feed.scrollTop = feed.scrollHeight;
  renderChats();
  input.focus();
}

/* ---------------- models ---------------- */
async function loadModels(){
  try {
    const r = await fetch("/api/models").then(async x => ({ok:x.ok, data:await x.json()}));
    const d = r.data;
    if (d.models) modelDefault = d.default;
    const models = d.models && d.models.length ? d.models : (modelDefault ? [modelDefault] : []);
    modelSel.innerHTML = "";
    models.forEach(m => {
      const o = document.createElement("option");
      o.value = m; o.textContent = m;
      if (m === (current && current.model) || m === modelDefault) o.selected = true;
      modelSel.appendChild(o);
    });
    if (current) modelSel.value = current.model;
    $("ollamaDot").classList.toggle("ok", !!r.data.models);
    $("ollamaState").textContent = r.data.models ? "Ollama online" : "Ollama offline";
    $("ollamaHost").textContent = "local · " + (d.ollama || "ollama");
  } catch {
    $("ollamaDot").classList.remove("ok");
    $("ollamaState").textContent = "Ollama offline";
  }
  if (modelDefault && !modelSel.value) modelSel.value = modelDefault;
}

/* ---------------- images ---------------- */
function renderPrev(){
  prevRow.classList.toggle("on", pendingImages.length>0);
  prevRow.innerHTML = "";
  pendingImages.forEach((u,i) => {
    const d = document.createElement("div"); d.className="prev";
    d.innerHTML = `<img src="${u}"><button class="rm">✕</button>`;
    d.querySelector(".rm").onclick = () => { pendingImages.splice(i,1); renderPrev(); };
    prevRow.appendChild(d);
  });
}
async function attach(files){
  for (const f of files){
    const fd = new FormData(); fd.append("file", f);
    const r = await fetch("/api/upload", {method:"POST", body:fd});
    const d = await r.json();
    if (!r.ok) { flash(d.error || "upload failed"); continue; }
    pendingImages.push(d.url);
  }
  fileIn.value = ""; renderPrev();
}

/* ---------------- send ---------------- */
function flash(msg, ok=false){
  $("statusLine").textContent = msg;
  $("statusLine").className = ok ? "" : "err";
  setTimeout(()=>{ $("statusLine").textContent=""; }, 6000);
}
async function send(){
  if (busy) return;
  const text = input.value.trim();
  if (!text && !pendingImages.length) return;
  if (!current) await newChatLocal();
  clearEmpty();
  input.value = ""; autosize();
  addMessage("user", text || "(image)", {images: pendingImages});
  const images = pendingImages; pendingImages = []; renderPrev();

  busy = true; setSend(false);
  const stickEl = (() => { const stick = atBottom();
    const n = document.createElement("div"); n.className="msg assistant";
    n.innerHTML = `<div class="avatar">🏠</div><div class="bubble"><div class="meta"><span>Home Agent · ${esc(modelSel.value)}</span><span class="t">…</span></div>
      <div class="content"><div class="shimmer"></div></div></div>`;
    inner.appendChild(n); if (stick) feed.scrollTop = feed.scrollHeight; return n; })();
  const contentEl = stickEl.querySelector(".content");
  const metaEl = stickEl.querySelector(".meta");

  const t0 = performance.now();
  controller = new AbortController();
  let acc = "";
  try {
    const resp = await fetch(`/api/chats/${current.id}/messages`, {
      method:"POST", headers:{"Content-Type":"application/json"},
      body: JSON.stringify({text, images}), signal: controller.signal,
    });
    if (!resp.ok) throw new Error((await resp.json()).error || resp.statusText);
    const reader = resp.body.getReader();
    const dec = new TextDecoder(); let buf = "";
    while (true){
      const {done, value} = await reader.read();
      if (done) break;
      buf += dec.decode(value, {stream:true});
      let i;
      while ((i = buf.indexOf("\n")) >= 0){
        const line = buf.slice(0,i).trim(); buf = buf.slice(i+1);
        if (!line) continue;
        const ev = JSON.parse(line);
        if (ev.type === "delta"){ acc += ev.content;
          contentEl.innerHTML = renderMarkdown(acc) + `<span class="cursor"></span>`;
          if (atBottom()) feed.scrollTop = feed.scrollHeight;
        } else if (ev.type === "error"){
          contentEl.insertAdjacentHTML("beforeend", `<p style="color:var(--err)">⚠ ${esc(ev.error)}</p>`);
        }
      }
    }
    contentEl.innerHTML = renderMarkdown(acc) || `<i style="color:var(--dim)">(no response)</i>`;
    const ms = Math.round(performance.now() - t0);
    metaEl.innerHTML = `<span>Home Agent · ${esc(modelSel.value)} · ${(ms/1000).toFixed(1)}s</span><span class="t">${esc(now())}</span>`;
    bindCopy(contentEl);
    loadChats(); // refresh titles/counts
  } catch (e){
    if (e.name !== "AbortError") contentEl.innerHTML = `<span style="color:var(--err)">⚠ ${esc(e.message)}</span>`;
    if (e.name === "AbortError") flash("Stopped.");
  } finally {
    busy = false; setSend(true); controller = null;
    feed.scrollTop = feed.scrollHeight;
  }
}
function setSend(on){
  const b = $("sendBtn");
  if (on){ b.className="send"; b.textContent="➤"; b.disabled = !(input.value.trim()||pendingImages.length); b.title="Send"; }
  else { b.className="send stop"; b.textContent="■"; b.disabled=false; b.title="Stop"; }
}
function bindCopy(scope){
  scope.querySelectorAll("pre .copy").forEach(btn => {
    btn.onclick = () => {
      navigator.clipboard.writeText(btn.parentElement.querySelector("code").innerText);
      btn.textContent = "copied ✓"; setTimeout(()=>btn.textContent="copy", 1200);
    };
  });
}

/* ---------------- events ---------------- */
function autosize(){ input.style.height="auto"; input.style.height = Math.min(input.scrollHeight, 260)+"px"; }
input.addEventListener("input", ()=>{ autosize(); setSend(!busy); });
input.addEventListener("keydown", e => {
  if (e.key === "Enter" && !e.shiftKey){ e.preventDefault(); send(); }
});
$("sendBtn").onclick = () => { busy ? controller && controller.abort() : send(); };
$("newChat").onclick = newChat;
$("attachBtn").onclick = () => fileIn.click();
fileIn.onchange = () => fileIn.files.length && attach([...fileIn.files]);
$("refreshModels").onclick = loadModels;
document.addEventListener("dragover", e => e.preventDefault());
document.addEventListener("drop", e => {
  e.preventDefault();
  if ([...e.dataTransfer.files].some(f=>f.type.startsWith("image/")))
    attach([...e.dataTransfer.files].filter(f=>f.type.startsWith("image/")));
});

/* ---------------- init ---------------- */
(async () => {
  await loadModels();
  await loadChats();
  if (chats.length){ await openChat(chats[0].id); } else { await newChatLocal(); }
  setSend(false); input.focus();
})();
