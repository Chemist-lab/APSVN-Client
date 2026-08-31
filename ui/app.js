// APSVN фронтенд: тонкий шар над pywebview API (window.pywebview.api)
//
// Рішення за результатами розбору відмов:
// * звірка з сервером УВІМКНЕНА завжди — інакше чужі локи стають видимі лише
//   після ручного натискання, а художник дізнається про зайнятий файл аж
//   наприкінці коміту;
// * опитування — ланцюжком setTimeout, а не setInterval: повільна відповідь
//   більше не накопичує чергу запитів;
// * один запит одночасно (inflight) — опитування не стає в чергу за комітом;
// * лічильник gen: відповідь, що прийшла ПІСЛЯ перемикання проєкту, малюватися
//   не повинна — інакше під назвою одного проєкту видно файли іншого;
// * слово «повернути» в інтерфейсі не вживається взагалі. Було два різні
//   «повернути»: одне відкидало денну роботу, друге тягнуло стару версію з
//   історії. Тепер це «✖ Відкинути мої зміни» і «⟲ Відновити цю версію»,
//   і вони ніколи не видимі одночасно.

let st = null, selected = new Set(), drafts = {}, hist = null;
let gen = 0, inflight = null, inflightGen = -1, timer = null, view = "files";
let lastFilesSig = null;          // підпис останньо мальованого списку

/* --- іконки типів файлів ------------------------------------------------
   Не возимо картинки з собою: логотипи Blender і Unreal чужі, та й іконка з
   системи завжди відповідає тому, що в людини справді встановлено. Windows
   відповідає за ~15 мс на розширення, тож питаємо один раз і памʼятаємо —
   разом із відповіддю «нічого немає», щоб не смикати систему щоопитування. */
const ICONS = new Map();          // ".blend" -> data:URI | ""
let iconsPending = false;

function extOf(name, isDir) {
  if (isDir) return "<dir>";
  const i = name.lastIndexOf(".");
  return i > 0 ? name.slice(i).toLowerCase() : "";
}

// Іконка як елемент: картинка, якщо система її дала, інакше старий значок.
function iconEl(cls, name, isDir, fallback) {
  const ext = extOf(name, isDir);
  const uri = ICONS.get(ext);
  if (uri) {
    const img = document.createElement("img");
    img.className = cls + " img"; img.src = uri; img.alt = "";
    return img;
  }
  const d = document.createElement("div");
  d.className = cls; d.textContent = fallback;
  return d;
}

async function wantIcons(names, dirs) {
  const need = [];
  for (const n of names) {
    const e = extOf(n, false);
    if (e && !ICONS.has(e) && !need.includes(e)) need.push(e);
  }
  if (dirs && !ICONS.has("<dir>")) need.push("<dir>");
  if (!need.length || iconsPending) return;
  iconsPending = true;
  let got;
  try { got = await api().icons(need); }
  catch (e) { got = {}; }
  finally { iconsPending = false; }
  for (const e of need) ICONS.set(e, got[e] || "");   // "" = питали, немає
  if (Object.keys(got).length) {
    // рядки перемалюються самі: URI входить у їхній підпис
    if (view === "browse") { if (brDir) renderDir(brDir); }
    else renderFiles();
  }
}

const $ = id => document.getElementById(id);
const api = () => window.pywebview.api;
const clean = e => String(e && e.message ? e.message : e)
  .replace(/^[\w.]*Error:\s*/, "").trim();
const pid = () => (st && st.pid) || "";

function toast(t, ms) {
  if (!t) return;
  const e = $("toast"); e.textContent = t;
  e.classList.remove("hidden"); clearTimeout(e._t);
  e._t = setTimeout(() => e.classList.add("hidden"), ms || 5000);
}
function busy(on, text) {
  $("busy-t").textContent = text || "Working…";
  $("busy").classList.toggle("hidden", !on);
  if (on) startProgress(); else stopProgress();
}

/* --- власне вікно запитання ---------------------------------------------
   Системне confirm() показує «127.0.0.1:16827 says» із випадковим портом
   щоразу — виглядає як збій програми. Своє вікно ще й уміє більше: окремі
   рядки замість купи \n, таблицю фактів і «більше не питати».

   Текст приймаємо СПИСКОМ рядків, а не одним рядком з переносами: так у
   коді немає жодного екранування, а у вікні — нормальні абзаци. */
function ask(o) {
  return new Promise(resolve => {
    const box = $("m-box");
    box.className = "mbox" + (o.danger ? " danger" : "");
    $("m-title").textContent = o.title || "";

    const t = $("m-text");
    t.innerHTML = "";
    for (const line of (o.lines || [])) {
      const d = document.createElement("div");
      d.className = "p" + (line.warn ? " warn-line" : "") +
                    (line.bad ? " bad-line" : "");
      d.textContent = line.text != null ? line.text : line;
      t.append(d);
    }
    if (o.facts && o.facts.length) {
      const f = document.createElement("div");
      f.className = "facts";
      for (const [k, v] of o.facts) {
        const r = document.createElement("div");
        r.className = "r";
        const a = document.createElement("span"); a.textContent = k;
        const b = document.createElement("b"); b.textContent = v;
        r.append(a, b); f.append(r);
      }
      t.append(f);
    }

    const chkWrap = $("m-chk-wrap"), chk = $("m-chk");
    chk.checked = false;
    chkWrap.classList.toggle("hidden", !o.remember);
    $("m-chk-t").textContent = o.remember || "";

    const ok = $("m-ok"), alt = $("m-alt"), cancel = $("m-cancel");
    ok.textContent = o.ok || "OK";
    ok.className = "primary" + (o.danger ? " bad" : "");
    cancel.textContent = o.cancel || "Cancel";
    alt.textContent = o.alt || "";
    alt.classList.toggle("hidden", !o.alt);

    const done = res => {
      $("modal").classList.add("hidden");
      document.removeEventListener("keydown", onKey, true);
      resolve(Object.assign({ ok: false, alt: false, remember: chk.checked }, res));
    };
    const onKey = e => {
      if (e.key === "Escape") { e.preventDefault(); done({}); }
      if (e.key === "Enter") { e.preventDefault(); done({ ok: true }); }
    };
    ok.onclick = () => done({ ok: true });
    alt.onclick = () => done({ alt: true });
    cancel.onclick = () => done({});
    $("modal").onclick = e => { if (e.target === $("modal")) done({}); };
    document.addEventListener("keydown", onKey, true);

    $("modal").classList.remove("hidden");
    ok.focus();
  });
}

function pref(name) {
  return !!(st && st.prefs && st.prefs[name]);
}

/* --- смуга поступу ----------------------------------------------------- */
// Показуємо рівно те, що svn справді повідомляє:
//  * качання однієї версії — точні відсотки (розмір відомий наперед);
//  * оновлення/завантаження/здача — «файл N з M»;
//  * фаза передачі даних — рух без відсотків, бо svn там мовчить, і будь-яке
//    число було б вигаданим.
let progTimer = null, sendStart = 0;

function mb(n) {
  if (n == null) return "";
  if (n >= 1073741824) return (n / 1073741824).toFixed(1) + " GB";
  if (n >= 1048576) return (n / 1048576).toFixed(1) + " MB";
  if (n >= 1024) return Math.round(n / 1024) + " KB";
  return n + " B";
}

function startProgress() {
  clearInterval(progTimer);
  $("bar-wrap").classList.add("hidden");
  $("bar").classList.remove("indet");
  $("bar").style.width = "0";
  sendStart = 0;
  progTimer = setInterval(async () => {
    let e = null;
    try { e = await api().progress(); } catch (err) { return; }
    if (!e) return;
    $("bar-wrap").classList.remove("hidden");
    const bar = $("bar");
    if (e.pct != null) {
      bar.classList.remove("indet");
      bar.style.width = e.pct + "%";
    } else {
      bar.style.width = "";        // інакше вбудована ширина переб'є .indet
      bar.classList.add("indet");
    }
    // svn не звітує про хід самої передачі, тож замість тиші показуємо, що
    // саме зараз відбувається і скільки вже триває
    if (e.phase === "send" || e.phase === "finalize") {
      if (!sendStart) sendStart = Date.now();
      const secs = Math.round((Date.now() - sendStart) / 1000);
      $("busy-sub").textContent =
        (secs > 2 ? mmss(secs) + " so far — " : "") +
        "svn reports nothing while sending; the window is not stuck";
    } else {
      sendStart = 0;
      $("busy-sub").textContent = e.file || "please keep this window open";
    }
    $("busy-t").textContent = progText(e);
  }, 400);
}

// Швидкість показуємо ЛИШЕ там, де вона справді виміряна — тобто на качанні
// однієї версії, де відомі й байти, і розмір. Для заливання лічильники читань
// дають 1.0-2.0x обсягу залежно від форми коміту, тож число було б завищеним.
function rateOf(e) {
  return e.kind === "download" && e.rate > 65536 ? " · " + mb(e.rate) + "/s" : "";
}

// Залишок часу. На качанні він точний, на заливанні — оцінка за швидкістю,
// заміряною на попередніх передачах, тому з «≈».
function etaOf(e) {
  if (e.eta == null) return "";
  const approx = e.kind === "upload" ? "≈ " : "";
  return e.eta < 5 ? " · almost done"
                   : " · " + approx + mmss(e.eta) + " left";
}

function mmss(s) {
  return s < 60 ? s + "s" : Math.floor(s / 60) + "m " + (s % 60) + "s";
}

function stopProgress() {
  clearInterval(progTimer);
  progTimer = null;
  $("bar-wrap").classList.add("hidden");
}

function progText(e) {
  if (e.phase === "receive") {
    const of = e.total_bytes ? " of " + mb(e.total_bytes) : "";
    return "Downloading — " + mb(e.bytes) + of +
           (e.pct != null ? " (" + e.pct + "%)" : "") + rateOf(e) + etaOf(e);
  }
  if (e.phase === "send")
    return "Sending file data…" +
           (e.total_bytes ? " — " + mb(e.total_bytes) + " to upload" : "") +
           etaOf(e);
  if (e.phase === "finalize") return "Finishing up on the server…";
  const verb = e.kind === "upload" ? "Uploading" : "Downloading";
  if (e.total) return verb + " — file " + e.done + " of " + e.total +
                       (e.pct != null ? " (" + e.pct + "%)" : "");
  return verb + " — " + e.done + (e.done === 1 ? " file" : " files");
}

/* --- стан ------------------------------------------------------------- */

function refresh() {
  // Перевикористовуємо запит, що вже летить, ЛИШЕ якщо він про той самий
  // проєкт. Інакше перемикання поверталo б обіцянку старого проєкту, вона
  // сама себе відкидала за gen — і екран до наступного опитування показував
  // би чужі файли під новою назвою.
  if (inflight && inflightGen === gen) return inflight;
  const mine = gen;
  const pr = _refresh(mine).finally(() => {
    if (inflightGen === mine) inflight = null;
  });
  inflight = pr;
  inflightGen = mine;
  return pr;
}

async function _refresh(mine) {
  let s;
  try {
    s = await api().state(true);              // завжди звіряємось із сервером
  } catch (e) {
    toast("Could not refresh: " + clean(e));
    return;
  }
  if (mine !== gen) return;                   // проєкт уже перемкнули
  st = s;

  if (!s.configured) {                        // майстер — лише коли проєктів 0
    showSetup(false);
    return;
  }
  $("setup").classList.add("hidden");
  $("main").classList.remove("hidden");
  renderProjects();

  $("h-rev").textContent = s.busy ? "refreshing…"
    : "your copy: commit " + (s.info ? s.info.revision : "?");
  $("h-wc").textContent = s.wc || "";
  // Саме ФАЙЛИ, а не різниця ревізій: після власної здачі svn підіймає
  // ревізію лише зданих шляхів, тож корінь копії лишається на старому числі й
  // людині писало «відстаєш на 1» відразу після того, як вона сама все здала.
  const inc = s.incoming_n || 0;
  $("h-behind").textContent = inc
    ? inc + (inc === 1 ? " file to get" : " files to get") +
      " — click “Get latest”" : "";
  $("h-behind").classList.toggle("hidden", !inc);
  // Тост про конфлікти живе 8 секунд, а групу «Needs your decision» можна
  // згорнути — тож людина могла відвернутись і не дізнатись нічого. Цей
  // рядок висить, доки конфлікт є.
  const nconf = ((s.files || []).filter(f => f.status === "conflicted")).length;
  $("h-conflict").textContent = nconf
    ? "⚠ " + nconf + (nconf === 1 ? " file needs your decision"
                                       : " files need your decision") : "";
  $("h-conflict").classList.toggle("hidden", !nconf);
  $("b-update").classList.toggle("has-work", !!inc);
  $("u-hint").textContent = inc
    ? (inc === 1 ? "1 file waiting for you" : inc + " files waiting for you")
    : "nothing new right now";
  $("c-keep").checked = pref("keep_locks");
  $("h-warn").textContent = s.warn || "";
  $("h-warn").classList.toggle("hidden", !s.warn);
  renderMoved(s);

  if (s.broken) { showBroken(s); return; }
  showView(view);
  // Опитування йде кожні 10 с, тож перемальовуємо список лише коли
  // дані справді змінилися — інакше рядки смикалися б просто під курсором,
  // а напівнабраний коментар чи відкрите меню губилися б.
  const sig = JSON.stringify([s.name, s.files || []]);
  if (sig !== lastFilesSig) {
    lastFilesSig = sig;
    renderFiles();
  } else {
    syncBar();
  }
}

// Сервер відповів «проєкт переїхав». Нову адресу пропонує САМ сервер, тож
// мовчки за нею йти не можна — показуємо її людині й чекаємо згоди.
function renderMoved(s) {
  const box = $("h-moved");
  if (!s.moved_to) { box.classList.add("hidden"); box._sig = null; return; }
  if (box._sig === s.moved_to) return;   // не перебудовуємо щодесять секунд
  box._sig = s.moved_to;
  box.innerHTML = "";
  const t = document.createElement("div");
  t.textContent = "The server says this project has moved to:";
  const u = document.createElement("div");
  u.className = "moved-url"; u.textContent = s.moved_to;
  const b = mini("Update the address", "", () => {
    ask({
      title: "Point this project at the new address?",
      lines: [s.moved_to, "Your files are not touched — only the address changes."],
      ok: "Update the address",
    }).then(a => {
      if (a.ok) act("relocate", [s.moved_to], "Updating the address…");
    });
  });
  box.append(t, u, b);
  box.classList.remove("hidden");
}

function renderProjects() {
  const sel = $("p-sel");
  const want = (st.projects || []).map(p => p.id + " " + p.name).join("|");
  if (sel._sig !== want) {                    // не перебудовуємо без потреби
    sel.innerHTML = "";
    for (const p of st.projects || []) {
      const o = document.createElement("option");
      o.value = p.id; o.textContent = p.name; o.title = p.wc || "";
      sel.append(o);
    }
    sel._sig = want;
  }
  sel.value = st.pid;
}

function showBroken(s) {
  for (const id of ["tab-files", "tab-history", "tab-browse", "filehist"])
    $(id).classList.add("hidden");
  $("tab-broken").classList.remove("hidden");
  $("brk-title").textContent = s.broken;
  $("brk-path").textContent = s.wc || "";
}

// внутрішні режими -> кнопки вкладок. Історія ОДНОГО файлу лишає підсвіченими
// «Файли», бо вона відкривається саме звідти.
const TAB_OF = { files: "files", file: "files", log: "history",
                 browse: "browse" };

function showView(v) {
  view = v;
  $("tab-broken").classList.add("hidden");
  $("filehist").classList.toggle("hidden", v !== "file");
  $("tab-files").classList.toggle("hidden", v !== "files");
  $("tab-history").classList.toggle("hidden", v !== "log");
  $("tab-browse").classList.toggle("hidden", v !== "browse");
  document.querySelectorAll(".tab").forEach(
    b => b.classList.toggle("on", b.dataset.tab === TAB_OF[v]));
}

/* --- список файлів ---------------------------------------------------- */

function chip(text, cls) {
  const c = document.createElement("span");
  c.className = "chip " + (cls || ""); c.textContent = text; return c;
}
function mini(text, cls, onclick) {
  const b = document.createElement("button");
  b.className = "mini " + (cls || ""); b.textContent = text; b.onclick = onclick;
  return b;
}

let liveSet = new Set();          // що взагалі можна позначити зараз
const openDirs = new Set();       // розгорнуті кинуті теки
const dirCache = {};              // їхній вміст, прочитаний один раз

function fmtSize(n) {
  if (n == null) return "";
  if (n >= 1073741824) return (n / 1073741824).toFixed(1) + " GB";
  if (n >= 1048576) return Math.round(n / 1048576) + " MB";
  if (n >= 1024) return Math.round(n / 1024) + " KB";
  return n + " B";
}

async function toggleDir(path) {
  if (openDirs.has(path)) { openDirs.delete(path); renderFiles(); return; }
  openDirs.add(path);
  if (!dirCache[path]) {
    try {
      dirCache[path] = await api().list_new_folder(path);
    } catch (e) {
      openDirs.delete(path);
      return toast(clean(e), 8000);
    }
  }
  renderFiles();
}

/* Розділи списку. Порядок перевірок = порядок важливості: перший збіг виграє.

   Окремо стоїть третій випадок у першій групі — «ти вже змінив файл, який
   тримає хтось інший». Він виглядає як звичайна твоя робота, але здати його
   неможливо, і дізнатися про це аж наприкінці коміту — найгірший момент.
   Тому він угорі, а не серед свого. */
const LOCAL_STATES = ["modified", "added", "missing", "unversioned",
                      "replaced", "deleted", "conflicted"];
const isMine = f => LOCAL_STATES.includes(f.status);

const GROUPS = [
  { id: "attention", title: "Needs your decision",
    hint: "you cannot submit these until they are sorted out",
    match: f => f.status === "conflicted" || f.lock_stale ||
                (isMine(f) && f.lock_owner && !f.lock_mine) },
  { id: "mine", title: "Your work",
    hint: "your changes and the files you hold",
    match: f => isMine(f) || f.lock_mine },
  { id: "others", title: "Locked by somebody else",
    hint: "wait until they submit and release",
    match: f => f.lock_owner && !f.lock_mine },
  { id: "incoming", title: "Coming from the team",
    hint: "click “Get latest” to pick these up",
    match: f => f.remote_change },
];

const collapsed = new Set();

function bucket(files) {
  const out = {};
  for (const g of GROUPS) out[g.id] = [];
  const rest = [];
  for (const f of files) {
    const g = GROUPS.find(x => x.match(f));
    (g ? out[g.id] : rest).push(f);
  }
  return { out, rest };
}

function groupHeader(g, n) {
  const h = document.createElement("div");
  h.className = "grp";
  const tw = document.createElement("span");
  tw.className = "gtw"; tw.textContent = collapsed.has(g.id) ? "▸" : "▾";
  const t = document.createElement("span");
  t.className = "gt"; t.textContent = g.title;
  const c = document.createElement("span");
  c.className = "gn"; c.textContent = n;
  const hint = document.createElement("span");
  hint.className = "gh"; hint.textContent = g.hint;
  h.append(tw, t, c, hint);
  h.onclick = () => {
    collapsed.has(g.id) ? collapsed.delete(g.id) : collapsed.add(g.id);
    renderFiles();
  };
  return h;
}

// Перемальовування без миготіння. Раніше список щоразу збирався з нуля
// (box.innerHTML = "" і тисяча нових вузлів), тож при кожному опитуванні
// скидалася прокрутка, зникала підсвітка під курсором і все видиме на мить
// «промигувало». Тепер рядок із тим самим підписом ПЕРЕЇЖДЖАЄ у новий
// порядок живим вузлом, а підміна відбувається одним replaceChildren() —
// браузер ніколи не бачить порожнього списку.
function reconcile(box, items) {
  const have = new Map();
  for (const n of box.children) if (n.dataset.k) have.set(n.dataset.k, n);
  const out = [];
  for (const [key, sig, make] of items) {
    const prev = have.get(key);
    if (prev && prev.dataset.s === sig) { out.push(prev); continue; }
    const node = make();
    node.dataset.k = key;
    node.dataset.s = sig;
    out.push(node);
  }
  const top = box.scrollTop;
  box.replaceChildren(...out);
  box.scrollTop = top;                // replaceChildren скидає прокрутку
}

function renderFiles() {
  const box = $("files");
  const files = (st && st.files) || [];

  // прибираємо з вибору те, чого вже немає або що не можна здавати
  const live = new Set(files
    .filter(f => f.status !== "conflicted" && !(f.lock_owner && !f.lock_mine))
    .map(f => f.path));
  liveSet = live;                       // «виділити все» працює по верхньому рівню
  // Файли всередині кинутих тек у liveSet не входять (інакше лічильник рахував
  // би тисячі), але вибір із них треба зберігати — інакше позначене зникало б
  // при кожному опитуванні.
  const keep = new Set(live);
  for (const f of files) {
    if (!f.dir || !dirCache[f.path]) continue;
    for (const c of dirCache[f.path].files) keep.add(c.path);
  }
  for (const p of Array.from(selected)) if (!keep.has(p)) selected.delete(p);

  $("empty").textContent = "No local changes in “" + (st.name || "") +
    "” 🎉";
  $("empty").classList.toggle("hidden", files.length !== 0);

  const { out, rest } = bucket(files);
  // Згорнута група не має ховати конфлікт: людина згортає її вранці, а по
  // обіді конфлікт приїжджає й лишається невидимим до першої відмови здачі.
  if ((out.attention || []).some(f => f.status === "conflicted"))
    collapsed.delete("attention");
  const items = [];
  const put = f => {
    // у підпис іде все, від чого залежить вигляд рядка — інакше
    // перевикористаний вузол показував би вчорашній стан
    items.push(["f:" + f.path,
                JSON.stringify([f, selected.has(f.path), openDirs.has(f.path),
                                ICONS.get(extOf(f.path, f.dir)) ? 1 : 0]),
                () => fileRow(f)]);
    if (f.dir && openDirs.has(f.path)) childItems(items, f);
  };
  for (const g of GROUPS) {
    const rows = out[g.id];
    if (!rows.length) continue;
    const n = rows.length;
    items.push(["g:" + g.id, n + "|" + collapsed.has(g.id),
                () => groupHeader(g, n)]);
    if (!collapsed.has(g.id)) rows.forEach(put);
  }
  rest.forEach(put);
  reconcile(box, items);
  syncBar();
  wantIcons(files.filter(f => !f.dir).map(f => f.path),
            files.some(f => f.dir));
}

function fileRow(f) {
    const blocked = f.status === "conflicted" || !!(f.lock_owner && !f.lock_mine);
    const row = document.createElement("div");
    row.className = "f" + (f.status === "conflicted" ? " conflict" : "");

    const cb = document.createElement("input");
    cb.type = "checkbox"; cb.checked = selected.has(f.path); cb.disabled = blocked;
    cb.onchange = () => {
      cb.checked ? selected.add(f.path) : selected.delete(f.path); syncBar();
    };

    if (f.dir) {
      // кинута тека: розгортається на вимогу, бо всередині можуть бути тисячі
      // файлів, а такий список щоразу перемальовувався б і був би нечитабельним
      const tw = document.createElement("button");
      tw.className = "twisty";
      tw.textContent = openDirs.has(f.path) ? "▾" : "▸";
      tw.onclick = () => toggleDir(f.path);
      row.append(tw);
    }

    const p = document.createElement("div");
    p.className = "p" + (f.dir ? " dirname" : " link");
    p.textContent = f.path;
    if (f.dir) {
      p.title = "click the triangle to see what is inside";
      p.onclick = () => toggleDir(f.path);
    } else {
      p.title = "show what happened to this file";
      p.onclick = () => openHistory(f.path);
    }
    row.append(cb, iconEl("fico", f.path, f.dir, f.dir ? "📁" : "📄"), p);

    if (f.status_text) row.append(chip(f.status_text, f.status));
    if (f.remote_change) row.append(chip("newer on the server", "remote"));
    if (f.dir) {
      row.append(chip(f.n_files + (f.counted_all === false ? "+" : "") +
                      (f.n_files === 1 ? " file" : " files") +
                      (f.bytes ? " · " + fmtSize(f.bytes) : "")));
    }

    if (f.status === "conflicted") {
      const k = f.conflict_kind || "text";
      const moved = k === "tree" || k === "obstructed";
      // Кожен вид конфлікту вимагає СВОЇХ слів: «взяти версію колеги» на
      // видаленому файлі означає «погодитись, що файлу більше немає», і
      // сказати це треба прямо, а не ховати за спільним формулюванням.
      const why = {
        text: [],
        tree: ["Your colleague moved or deleted this file while you were " +
               "working on it."],
        obstructed: ["Your own file is sitting where the team’s file " +
                     "should be. Nothing of yours has been overwritten yet."],
        prop: ["The file’s contents are fine — only its settings clash."],
      }[k];

      row.append(mini(moved ? "keep my file" : "keep my version", "", () => {
        ask({
          title: moved ? "Keep your file?" : "Keep your version?",
          lines: why.concat([
            moved ? "“" + f.path + "” stays as yours and goes back " +
                    "to the project as a new file."
                  : "Your colleague’s version of “" + f.path +
                    "” will be thrown away.",
            "A copy of the file as it is right now goes to “Safety " +
            "copies” first."]),
          ok: moved ? "Keep my file" : "Keep mine", danger: true,
        }).then(a => {
          if (a.ok) act("do_resolve", [[f.path], true, "mine"],
                        "Keeping your version…");
        });
      }));

      row.append(mini(moved ? "take what the team has" :
                      "take my colleague’s version", "danger", () => {
        ask({
          title: moved ? "Go with the team’s version?"
                       : "Take your colleague’s version?",
          lines: why.concat([
            moved ? "“" + f.path + "” will disappear from your " +
                    "folder, the same as it did for everybody else."
                  : "Your changes in “" + f.path + "” will be gone.",
            "A copy goes to “Safety copies” first — that is the " +
            "only way back.",
            { text: "Nothing else can undo this.", bad: true }]),
          ok: moved ? "Go with the team" : "Take theirs", danger: true,
        }).then(a => {
          if (a.ok) act("do_resolve", [[f.path], false, "theirs"],
                        "Taking your colleague’s version…");
        });
      }));

      // Третій вихід — для того, хто вже звів обидві правки руками. Без нього
      // «keep my version» підставляла доконфліктну копію й тихо викидала цю
      // роботу. Для бінарника змісту не має: руками .blend не зводять.
      if (k === "text" && !f.binary) {
        row.append(mini("I sorted it out myself", "", () => {
          ask({
            title: "Use the file as it is now?",
            lines: ["Pick this only if you opened “" + f.path + "” " +
                    "and merged both versions by hand.",
                    "APSVN will take exactly what is on your disk right now " +
                    "and mark the conflict as done."],
            ok: "Use what I have",
          }).then(a => {
            if (a.ok) act("do_resolve", [[f.path], true, "working"],
                          "Marking it sorted…");
          });
        }));
      }
    } else {
      if (f.status === "modified" || f.status === "missing") {
        row.append(mini("✖ Discard my changes", "danger", () => {
          ask({
            title: "Discard your changes?",
            lines: ["“" + f.path + "” will become what is on the server right now.",
                    { text: "Everything done since the last submit will be gone for good.",
                      bad: true }],
            ok: "Discard my changes", danger: true,
          }).then(a => {
            if (a.ok) act("do_revert", [[f.path]], "Discarding changes…");
          });
        }));
      }
      if (!f.dir) {                        // теку не займають — займають файли
        const lb = document.createElement("button");
        lb.className = "lockbtn";
        if (f.lock_stale) {
          lb.classList.add("stale"); lb.textContent = "your lock was removed — get latest";
          lb.onclick = () => act("do_update", [], "Getting latest…");
        } else if (f.lock_mine) {
          lb.classList.add("mine"); lb.textContent = "🔒 mine · release";
          lb.onclick = () => act("do_unlock", [[f.path]], "Releasing…");
        } else if (f.lock_owner) {
          lb.classList.add("other"); lb.textContent = "🔒 " + f.lock_owner;
          lb.disabled = true;
          lb.title = "locked until your colleague submits their work";
        } else {
          lb.textContent = "🔓 lock";
          lb.onclick = () => act("do_lock", [[f.path]], "Locking…");
        }
        row.append(lb);
      }
    }
    return row;
}

/* Вміст розгорнутої теки. Позначена тека означає «здати все, що в ній», тож
   галочки всередині тоді стоять і не редагуються — інакше було б незрозуміло,
   що саме поїде. */
// Вміст розгорнутої теки — такими самими ключованими записами, як і верхній
// рівень: у кинутій теці буває пара тисяч файлів, і саме вони мигали
// найпомітніше.
function childItems(items, dir) {
  const data = dirCache[dir.path];
  if (!data) {
    items.push(["cw:" + dir.path, "wait", () => {
      const w = document.createElement("div");
      w.className = "child dim"; w.textContent = "reading folder…";
      return w;
    }]);
    return;
  }
  const whole = selected.has(dir.path);
  for (const c of data.files) {
    const on = whole || selected.has(c.path);
    items.push(["c:" + c.path,
                JSON.stringify([c, on, whole,
                                ICONS.get(extOf(c.path, false)) ? 1 : 0]), () => {
      const row = document.createElement("div");
      row.className = "f child";
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.checked = on;
      cb.disabled = whole;
      cb.onchange = () => {
        cb.checked ? selected.add(c.path) : selected.delete(c.path);
        syncBar();
      };
      const p = document.createElement("div");
      p.className = "p";
      p.textContent = c.path.slice(dir.path.length + 1);
      p.title = c.path;
      row.append(cb, iconEl("fico", c.path, false, "📄"), p);
      if (c.binary) row.append(chip("needs locking", ""));
      return row;
    }]);
  }
  if (data.truncated) {
    items.push(["ct:" + dir.path, "cut", () => {
      const w = document.createElement("div");
      w.className = "child dim";
      w.textContent = "…too many files to list them all — tick the folder itself " +
                      "to submit everything inside";
      return w;
    }]);
  }
}

function syncBar() {
  const n = selected.size, m = liveSet.size;
  $("b-commit").textContent = n ? "⬆ Submit (" + n + ")" : "⬆ Submit";

  const bar = $("selbar"), cb = $("sel-all");
  bar.classList.toggle("hidden", !((st && st.files) || []).length);
  const allTop = m > 0 && [...liveSet].every(p => selected.has(p));
  cb.disabled = m === 0;
  cb.checked = allTop;
  // проміжний стан: позначено частину — інакше клік по «виділити все» після
  // ручного вибору виглядав би як «зняти все»
  cb.indeterminate = !allTop && n > 0;
  $("sel-all-t").textContent = allTop ? "Deselect all" : "Select all";
  $("sel-count").textContent = m
    ? (n ? n + " selected" : "nothing selected")
    : "nothing here can be submitted";
}

$("sel-all").onchange = () => {
  if ($("sel-all").checked) for (const p of liveSet) selected.add(p);
  else selected.clear();
  renderFiles();
};

/* --- історія одного файлу й відновлення версії ------------------------- */

async function openHistory(path) {
  busy(true, "Reading this file’s history…");
  try {
    hist = await api().file_history(path);
  } catch (e) { busy(false); return toast(clean(e), 8000); }
  busy(false);
  renderHistory();
  showView("file");
}

function renderHistory() {
  $("fh-title").textContent = "What happened to “" + hist.path + "”";
  const note = $("fh-note");
  // відкат поверх незданих змін знищив би їх безповоротно — тому не питаємо,
  // а відмовляємо, і одразу даємо обидва законні виходи
  if (hist.dirty) {
    note.innerHTML = "";
    note.append(document.createTextNode(
      "This file has changes you haven’t submitted. Submit them or discard them first — " +
      "otherwise they are gone for good. "));
    note.append(mini("⬆ Go to submit", "", () => {
      selected.add(hist.path); showView("files"); renderFiles();
      $("c-msg").focus();
    }));
    note.append(mini("✖ Discard my changes", "danger", () => {
      ask({
        title: "Discard your changes?",
        lines: ["“" + hist.path + "” will become what is on the server right now.",
                { text: "Everything done since the last submit will be gone for good.",
                  bad: true }],
        ok: "Discard my changes", danger: true,
      }).then(a => {
        if (a.ok)
          act("do_revert", [[hist.path]], "Discarding changes…")
            .then(() => openHistory(hist.path));
      });
    }));
    note.classList.remove("hidden");
  } else if (hist.locked_by) {
    note.textContent = "This file is locked by " + hist.locked_by +
      ". You can bring back a version once they submit their work.";
    note.classList.remove("hidden");
  } else {
    note.classList.add("hidden");
  }

  const box = $("fh-rows"); box.innerHTML = "";
  if (!hist.rows.length) {
    box.innerHTML = "<div class='empty'>No history yet — this file was never submitted</div>";
    return;
  }
  const ACT = { A: "added", M: "changed", D: "deleted", R: "replaced" };
  for (const r of hist.rows) {
    const d = document.createElement("div"); d.className = "hr";
    const head = document.createElement("div"); head.className = "meta";
    head.textContent = "commit " + r.rev + " · " + r.author + " · " + r.date +
      (ACT[r.action] ? " · " + ACT[r.action] : "");
    const m = document.createElement("div"); m.className = "m";
    m.textContent = r.msg || "(no note)";
    d.append(head, m);
    if (r.renamed_from) {
      const rn = document.createElement("div"); rn.className = "dim";
      rn.textContent = "back then it was called “" + r.renamed_from + "”";
      d.append(rn);
    }
    const bar = document.createElement("div"); bar.className = "hr-bar";
    bar.append(mini("👁 Save a copy…", "", () => saveAs(r.rev)));
    const rb = mini("⟲ Bring back this version", "warn", () => restore(r));
    rb.disabled = !!(hist.dirty || hist.locked_by);
    bar.append(rb);
    d.append(bar);
    box.append(d);
  }
}

async function saveAs(rev) {
  busy(true, "Fetching the old version… a big file can take a while");
  try { toast(await api().save_version_as(hist.path, rev), 9000); }
  catch (e) { toast(clean(e), 9000); }
  busy(false);
}

function restore(r) {
  const lines = ["This will not touch the history: the old version becomes the " +
                 "newest one, and you still have to submit it.",
                 "A copy of your current file is kept aside — see “Safety copies”."];
  if (hist.binary)
    lines.push({ text: "If this file is open in Blender right now, close it. " +
                       "Otherwise Blender will write back what it holds in " +
                       "memory and the version you brought back will be gone.",
                 warn: true });
  ask({
    title: "Bring back the version from " + r.date + "?",
    facts: [["File", hist.path], ["From", "commit " + r.rev],
            ["Author", r.author]],
    lines: lines,
    ok: "Bring it back",
  }).then(a => {
    if (!a.ok) return;
    busy(true, "Bringing back commit " + r.rev + "… a big file can take a while");
    api().restore_version(hist.path, r.rev)
      .then(m => toast(m, 10000))
      .catch(e => toast(clean(e), 10000))
      .then(() => { busy(false); showView("files"); return refresh(); });
  });
}

/* --- провідник проєкту -------------------------------------------------- */
// Дані тягнемо по одній теці, на вимогу: на копії з 2000 файлів це 24 КБ
// замість 505 КБ. Список НЕ перемальовується за таймером — інакше рядки
// пересортувалися б просто під курсором і клік потрапив би не в той файл.

let brPath = "", brSel = null, brBusy = false;
let brDir = null;                 // остання намальована тека — щоб перемалювати
                                  // її, коли доїдуть іконки
// дерево: які теки розгорнуті і що всередині кожної (кешуємо, бо той
// самий browse уже приніс список підтек — другий запит зайвий)
const treeOpen = new Set([""]);
let treeKids = {};

async function openDir(path) {
  if (brBusy) return;
  brBusy = true;
  const box = $("br-list");
  box.innerHTML = "<div class='empty'>Reading folder…</div>";
  let d;
  try {
    d = await api().browse(path);
  } catch (e) {
    box.innerHTML = "";
    brBusy = false;
    return toast(clean(e), 8000);
  }
  brBusy = false;
  brPath = d.path;
  brSel = null;
  treeKids[d.path] = d.entries.filter(e => e.kind === "dir" && !e.link);
  // шлях до поточної теки розгортаємо, щоб її було видно в дереві
  let acc = "";
  treeOpen.add("");
  for (const part of (d.path ? d.path.split("/") : [])) {
    acc = acc ? acc + "/" + part : part;
    treeOpen.add(acc);
  }
  renderCrumbs(d);
  renderDir(d);
  renderTree();
  sideEmpty();
}

/* --- дерево тек ---------------------------------------------------------- */

async function treeToggle(path) {
  if (treeOpen.has(path)) {
    treeOpen.delete(path);
    renderTree();
    return;
  }
  treeOpen.add(path);
  if (!treeKids[path]) {
    renderTree();                       // одразу показуємо «читаю…»
    try {
      const d = await api().browse(path);
      treeKids[path] = d.entries.filter(e => e.kind === "dir" && !e.link);
    } catch (e) {
      treeOpen.delete(path);
      renderTree();
      return toast(clean(e), 8000);
    }
  }
  renderTree();
}

function treeNode(item, depth) {
  const path = item ? item.path : "";
  const open = treeOpen.has(path);
  const kids = treeKids[path];

  const row = document.createElement("div");
  row.className = "tn" + (path === brPath ? " on" : "");
  row.style.paddingLeft = (6 + depth * 13) + "px";

  const tw = document.createElement("span");
  tw.className = "tw" + (item && item.nested ? " empty" : "");
  tw.textContent = open ? "▾" : "▸";
  tw.onclick = ev => { ev.stopPropagation(); treeToggle(path); };
  row.append(tw);

  const ic = document.createElement("span");
  ic.className = "ti";
  ic.textContent = item ? (item.nested ? "📦" : (open ? "📂" : "📁")) : "🗂";
  const lb = document.createElement("span");
  lb.className = "tl";
  lb.textContent = item ? item.name : (st.name || "project");
  row.append(ic, lb);
  if (item && item.new_inside) {
    const d = document.createElement("span");
    d.className = "dot"; d.title = "somebody submitted something in here";
    row.append(d);
  }
  row.onclick = () => { if (path !== brPath) openDir(path); };

  const box = document.createDocumentFragment();
  box.append(row);
  if (open) {
    if (!kids) {
      const w = document.createElement("div");
      w.className = "tn"; w.style.paddingLeft = (6 + (depth + 1) * 13) + "px";
      w.innerHTML = "<span class='tw empty'></span><span class='tl dim'>reading…</span>";
      box.append(w);
    } else {
      for (const k of kids) box.append(treeNode(k, depth + 1));
    }
  }
  return box;
}

function renderTree() {
  const box = $("br-tree");
  box.innerHTML = "";
  box.append(treeNode(null, 0));
}

function renderCrumbs(d) {
  const box = $("crumbs");
  box.innerHTML = "";
  const parts = d.path ? d.path.split("/") : [];
  const mk = (label, target, last) => {
    const b = document.createElement("button");
    b.className = "crumb" + (last ? " last" : "");
    b.textContent = label;
    if (!last) b.onclick = () => openDir(target);
    return b;
  };
  box.append(mk(st.name || "project", "", parts.length === 0));
  let acc = "";
  parts.forEach((p, i) => {
    acc = acc ? acc + "/" + p : p;
    const sep = document.createElement("span");
    sep.className = "crumb-sep"; sep.textContent = "›";
    box.append(sep, mk(p, acc, i === parts.length - 1));
  });
  const n = d.entries.length;
  $("br-count").textContent = n + (n === 1 ? " item" : " items") +
    (d.truncated ? " (too many to list them all)" : "");
}

function renderDir(d) {
  brDir = d;
  const box = $("br-list");
  box.innerHTML = "";
  if (!d.entries.length) {
    box.innerHTML = "<div class='empty'>This folder is empty</div>";
    return;
  }
  if (d.parent !== null) {
    const up = document.createElement("div");
    up.className = "e dir";
    up.innerHTML = "<div class='ico'>↰</div>";
    const nm = document.createElement("div");
    nm.className = "nm"; nm.textContent = "..";
    nm.onclick = () => openDir(d.parent);
    up.append(nm);
    box.append(up);
  }
  for (const it of d.entries) box.append(entryRow(it));
  wantIcons(d.entries.filter(e => e.kind !== "dir").map(e => e.name),
            d.entries.some(e => e.kind === "dir"));
}

function entryRow(it) {
  const row = document.createElement("div");
  row.className = "e " + it.kind + (it.on_disk ? "" : " ghost-row");

  // Ярлик лишається ярликом: система дала б іконку цілі, а тут важливо саме
  // те, що це не справжня тека проєкту.
  row.append(it.link ? iconEl("ico", "", false, "🔗")
                     : iconEl("ico", it.name, it.kind === "dir",
                              it.kind === "dir" ? "📁"
                                                : (it.binary ? "🎬" : "📄")));

  const nm = document.createElement("div");
  nm.className = "nm"; nm.textContent = it.name; nm.title = it.path;
  if (it.kind === "dir") {
    if (!it.nested && !it.link) nm.onclick = () => openDir(it.path);
  } else {
    row.onclick = () => selectFile(it, row);
    if (it.openable && it.on_disk) row.ondblclick = () => openIt(it);
  }
  row.append(nm);

  if (it.kind === "dir" && !it.nested && !it.link) {
    // Теки svn не блокує — блокуємо все, що в них. Числа беремо з сервера
    // ПЕРЕД дією, щоб у діалозі стояла правда, а не обіцянка.
    row.append(mini("🔓 lock folder", "", ev => {
      ev.stopPropagation();
      folderLock(it);
    }));
  }
  if (it.nested) row.append(chip("separate project", ""));
  if (it.link) row.append(chip("shortcut", ""));
  if (it.new_inside) row.append(chip("new inside", "remote"));
  if (it.status && !["normal", "none", "unversioned"].includes(it.status))
    row.append(chip(it.status_text, it.status));
  if (it.status === "unversioned" && it.on_disk) row.append(chip("new", "unversioned"));
  if (it.remote_change && it.on_disk) row.append(chip("newer on the server", "remote"));
  if (!it.on_disk) row.append(chip("not downloaded yet", "remote"));

  if (it.kind === "file") {
    const lb = document.createElement("button");
    lb.className = "lockbtn";
    if (it.lock_stale) {
      lb.classList.add("stale"); lb.textContent = "lock removed";
      lb.onclick = ev => { ev.stopPropagation(); act("do_update", [], "Getting latest…"); };
    } else if (it.lock_mine) {
      lb.classList.add("mine"); lb.textContent = "🔒 mine";
      lb.onclick = ev => {
        ev.stopPropagation();
        act("do_unlock", [[it.path]], "Releasing…").then(() => openDir(brPath));
      };
    } else if (it.lock_owner) {
      lb.classList.add("other"); lb.textContent = "🔒 " + it.lock_owner;
      lb.disabled = true;
      lb.title = "locked until your colleague submits their work";
    } else if (it.on_disk && it.status !== "unversioned") {
      lb.textContent = "🔓 lock";
      lb.onclick = ev => {
        ev.stopPropagation();
        act("do_lock", [[it.path]], "Locking…").then(() => openDir(brPath));
      };
    }
    row.append(lb);
  }

  const sz = document.createElement("div");
  sz.className = "sz"; sz.textContent = it.size == null ? "" : fmtSize(it.size);
  const dt = document.createElement("div");
  dt.className = "dt"; dt.textContent = it.mtime || "";
  row.append(sz, dt);
  return row;
}

/* Головна дія бінарника — «зайняти й відкрити». Порядок не косметичний:
   якщо відкрити спершу, а зайняти потім, людина попрацює в файлі, у який
   не має права писати, і зданий чужий день зникне при першому ж збереженні. */
async function openIt(it) {
  const free = it.binary && !it.lock_mine && !it.lock_owner;
  if (free && pref("lock_open_silent")) {     // людина попросила не питати
    return act("open_file", [it.path, true], "Locking and opening…")
      .then(() => openDir(brPath));
  }
  if (free) {
    const a = await ask({
      title: "Lock “" + it.name + "” before opening?",
      lines: ["Until you lock it, the file is read-only and Blender will not " +
              "let you save over it.",
              "Locking it makes it yours — your colleagues will see that you " +
              "are working on it."],
      ok: "Lock and open",
      alt: "Open read-only",
      remember: "Always lock when I open — stop asking",
    });
    if (a.remember && (a.ok || a.alt))
      api().set_pref("lock_open_silent", a.ok).catch(() => {});
    if (a.ok) {
      return act("open_file", [it.path, true], "Locking and opening…")
        .then(() => openDir(brPath));
    }
    if (!a.alt) return;
  }
  if (it.binary && it.lock_owner && !it.lock_mine) {
    const a = await ask({
      title: "“" + it.name + "” is locked by " + it.lock_owner,
      lines: ["You can look at it, but Blender will not let you save."],
      ok: "Open read-only",
    });
    if (!a.ok) return;
  }
  act("open_file", [it.path, false], "Opening…");
}

async function selectFile(it, row) {
  document.querySelectorAll("#br-list .e.on").forEach(x => x.classList.remove("on"));
  row.classList.add("on");
  brSel = it.path;
  const side = $("br-side");
  side.innerHTML = "<div class='br-empty'>Reading…</div>";
  let d = null;
  if (it.on_disk) {
    try { d = await api().file_details(it.path); } catch (e) { d = null; }
  }
  if (brSel !== it.path) return;          // людина вже клікнула інший файл
  renderSide(it, d);
}

function sideEmpty() {
  $("br-side").innerHTML = "<div class='br-empty'>Pick a file to see it here</div>";
}

function renderSide(it, d) {
  const side = $("br-side");
  side.innerHTML = "";
  if (d && d.preview) {
    const img = document.createElement("img");
    img.className = "br-thumb"; img.src = d.preview; img.alt = "";
    side.append(img);
  }
  const nm = document.createElement("div");
  nm.className = "br-name"; nm.textContent = it.name;
  side.append(nm);

  const fact = (k, v) => {
    if (v == null || v === "") return;
    const r = document.createElement("div");
    r.className = "br-fact";
    const a = document.createElement("span"); a.textContent = k;
    const b = document.createElement("b"); b.textContent = v;
    r.append(a, b); side.append(r);
  };
  fact("size", it.size == null ? "" : fmtSize(it.size));
  fact("changed", it.mtime);
  fact("state", it.status_text || (it.on_disk ? "unchanged" : "not downloaded yet"));
  if (it.lock_owner) fact("locked by", it.lock_mine ? "you" : it.lock_owner);
  if (d && !d.writable) fact("on disk", "read-only until locked");

  if (it.on_disk) {
    if (it.openable) {
      side.append(mini(it.binary && !it.lock_mine ? "🔓 Lock and open" : "▶ Open",
                       "", () => openIt(it)));
    }
    side.append(mini("📂 Show in folder", "", () => api().reveal(it.path)));
    side.append(mini("🕘 History", "", () => openHistory(it.path)));
  }
}

/* Зайняти цілу теку. Subversion лока на теку не має взагалі, тож це означає
   «зайняти кожен файл усередині». Тому в діалозі стоять справжні числа —
   скільки файлів, скільки вже наші, скільки тримає хтось інший. */
async function folderLock(it) {
  let s;
  busy(true, "Counting files…");
  try {
    s = await api().folder_stats(it.path);
  } catch (e) {
    busy(false);
    return toast(clean(e), 8000);
  }
  busy(false);
  if (!s.total) return toast("There is nothing to lock in this folder.");

  if (s.mine && s.mine === s.total - s.others_n) {
    const a = await ask({
      title: "Release “" + it.name + "”?",
      lines: ["You already hold every file you can in this folder."],
      facts: [["Locked by you", String(s.mine)]],
      ok: "Release them all",
    });
    if (a.ok)
      act("unlock_folder", [it.path], "Releasing the folder…")
        .then(() => openDir(brPath));
    return;
  }

  const facts = [["Files in this folder", String(s.total)]];
  if (s.mine) facts.push(["Already yours", String(s.mine)]);
  if (s.others_n)
    facts.push(["Held by somebody else",
                s.others_n + " (" + s.others.join(", ") + ") — skipped"]);
  const a = await ask({
    title: "Lock everything in “" + it.name + "”?",
    facts: facts,
    lines: ["Subversion cannot lock a folder itself, so APSVN locks each file " +
            "inside it, subfolders included.",
            "Your colleagues will not be able to edit them until you release " +
            "them."],
    ok: "Lock the folder",
  });
  if (!a.ok) return;
  act("lock_folder", [it.path], "Locking the folder…").then(() => openDir(brPath));
}

/* --- видалені файли ---------------------------------------------------- */

/* --- дії -------------------------------------------------------------- */

async function act(method, args, text) {
  busy(true, text);
  try {
    const r = await api()[method].apply(null, args || []);
    if (typeof r === "string") toast(r, 8000);
  } catch (e) {
    toast(clean(e), 9000);
  }
  busy(false);
  await refresh();
}

// Людина має бачити, ЩО саме зараз приїде: «оновитись» усліпу над текою,
// де лежить твій півдня роботи, страшно всім, хто вже обпікався.
const INCOMING_WORD = { added: "new", modified: "updated", deleted: "removed",
                        replaced: "replaced" };

$("b-update").onclick = async () => {
  const list = (st && st.incoming) || [];
  if (!list.length || pref("update_silent")) {
    // Нічого не приїде (або людина вже попросила не питати) — просто тягнемо.
    // Оновлення на порожньому не забороняємо: це ще й починка копії після збою.
    return act("do_update", [], "Getting the latest from the server…");
  }
  const facts = list.slice(0, 12).map(
    x => [x.path, INCOMING_WORD[x.kind] || x.kind]);
  if (list.length > facts.length)
    facts.push(["…and " + (list.length - facts.length) + " more", ""]);
  const a = await ask({
    title: list.length === 1 ? "1 file will come down"
                             : list.length + " files will come down",
    lines: ["Your own edits are not touched — only what changed on the " +
            "server is downloaded."],
    facts: facts,
    ok: "Get latest",
    remember: "Just get it — stop showing me this list",
  });
  if (a.ok && a.remember) api().set_pref("update_silent", true).catch(() => {});
  if (a.ok) act("do_update", [], "Getting the latest from the server…");
};
/* --- меню рідкісних дій -------------------------------------------------
   Кнопки лишились ті самі й з тими самими id, тож їхні обробники нижче не
   змінювались — переїхала тільки розмітка. Меню закривається від кліку
   будь-де й від Escape: інакше воно лишалося б висіти над панеллю після
   того, як людина передумала. */
function menuOpen(on) {
  const m = $("menu");
  const show = on === undefined ? m.classList.contains("hidden") : on;
  m.classList.toggle("hidden", !show);
  $("b-menu").classList.toggle("on", show);
  if (show) $("menu-name").textContent =
    ((st && st.name) || "") + ((st && st.version) ? "  ·  APSVN " + st.version : "");
}

$("b-menu").onclick = e => { e.stopPropagation(); menuOpen(); };

/* --- оновлення самої програми ------------------------------------------
   Перевіряємо раз при старті й мовчимо, якщо все свіже: програма, яка щоразу
   нагадує про себе, дратує швидше, ніж стара версія. */
let upInfo = null;

function showUpdateState() {
  const has = !!(upInfo && upInfo.newer);
  $("b-update-app").textContent = has
    ? "\u2b06 Update to " + upInfo.want : "\u2b06 Check for updates";
  $("b-menu").classList.toggle("has-news", has);
}

async function checkUpdate(quiet) {
  try { upInfo = await api().check_update(); }
  catch (e) { upInfo = null; }
  showUpdateState();
  if (quiet) return;

  if (!upInfo || upInfo.state === "offline" || upInfo.state === "error")
    return toast("Could not reach the update server \u2014 check your internet");
  if (upInfo.state === "none")
    return toast("No releases published yet");
  if (!upInfo.newer)
    return toast("You have the newest version (" + upInfo.have + ")");

  const lines = ["You have " + upInfo.have + ", the newest is " +
                 upInfo.want + "."];
  if (upInfo.notes) lines.push(upInfo.notes);
  lines.push("APSVN will close and open again by itself. Your projects, " +
             "passwords and files are not touched \u2014 only the program.");
  const a = await ask({
    title: "Update to " + upInfo.want + "?",
    lines: lines,
    facts: upInfo.size
      ? [["download", (upInfo.size / 1048576).toFixed(1) + " MB"]] : [],
    ok: "Update now", alt: "Open the release page",
  });
  if (a.alt) return api().open_link(upInfo.url);
  if (!a.ok) return;

  busy(true, "Downloading the update\u2026");
  try {
    const msg = await api().do_update_app();
    busy(false);
    await ask({ title: "Ready", lines: [msg], ok: "Close and update" });
    api().finish_update();
  } catch (e) {
    busy(false);
    toast(clean(e), 9000);
  }
}

$("b-update-app").onclick = () => { menuOpen(false); checkUpdate(false); };
for (const id of ["b-fix", "b-server", "b-forget", "b-update-app"])
  $(id).addEventListener("click", () => menuOpen(false));
// клік по самому меню не має його закривати — інакше пункт не встигне спрацювати
$("menu").onclick = e => e.stopPropagation();
document.addEventListener("click", () => menuOpen(false));
document.addEventListener("keydown", e => {
  if (e.key === "Escape" && !$("menu").classList.contains("hidden")) {
    e.stopPropagation();          // Escape тут закриває меню, а не модалку
    menuOpen(false);
  }
}, true);

$("b-open").onclick = () => api().open_folder();
$("b-rescue").onclick = () => api().open_rescue();
$("b-remote").onclick = async () => {
  busy(true, "Checking with the server…"); await refresh(); busy(false);
};
$("b-fix").onclick = () => {
  ask({
    title: "Repair the project?",
    lines: ["Use this if APSVN was closed in the middle of a transfer and now " +
            "says the project is busy.",
            "Your files are not touched."],
    ok: "Repair",
  }).then(a => { if (a.ok) act("do_cleanup", [], "Repairing…"); });
};
$("fh-back").onclick = () => { showView("files"); renderFiles(); };

$("b-commit").onclick = async () => {
  const msg = $("c-msg").value.trim();
  if (!selected.size) return toast("Tick what you want to submit");
  if (!msg) return toast("Write a short note about what you did — your team will see it in the history");
  busy(true, "Submitting… big files can take a while");
  try {
    toast(await api().do_commit(Array.from(selected), msg,
                               $("c-keep").checked), 9000);
    selected.clear(); $("c-msg").value = ""; delete drafts[pid()];
  } catch (e) { toast(clean(e), 9000); }
  busy(false);
  await refresh();
};

/* --- проєкти ---------------------------------------------------------- */

$("p-sel").onchange = async () => {
  const to = $("p-sel").value;
  if (!to || to === pid()) return;
  busy(true, "Switching project…");
  try {
    drafts[pid()] = $("c-msg").value;   // чернетка лишається у СВОГО проєкту
    await api().switch_project(to);
    gen++;                              // відповіді старого проєкту — за борт
    selected.clear();
    hist = null;
    view = "files";
    $("c-msg").value = drafts[to] || "";
    $("srv").classList.add("hidden");
    brPath = ""; brSel = null;
    treeKids = {}; treeOpen.clear(); treeOpen.add("");
    lastFilesSig = null;
    logRows = []; logRev = null;
    for (const k of Object.keys(revCache)) delete revCache[k];
  } catch (e) {
    toast(clean(e), 8000);
    $("p-sel").value = pid();
    busy(false);
    return;
  }
  await refresh();
  busy(false);
};

// Вибір «лишити локи» памʼятаємо: це властивість звички людини, а не
// одного коміту.
$("c-keep").onchange = () => {
  api().set_pref("keep_locks", $("c-keep").checked).catch(() => {});
  if (st && st.prefs) st.prefs.keep_locks = $("c-keep").checked;
};

$("p-add").onclick = () => showSetup(true);

/* Зміна адреси сервера. Окрема дія, а не тільки реакція на «проєкт переїхав»:
   сервер може змінити адресу так, що стара перестане відповідати взагалі —
   тоді підказки від нього не буде, і людині потрібен ручний шлях. Робоча копія
   лишається на місці: svn relocate звіряє UUID репозиторію й відмовиться, якщо
   вказати чужий сервер. */
function curProject() {
  return ((st && st.projects) || []).find(x => x.id === st.pid) || {};
}

$("b-server").onclick = () => {
  $("srv-url").value = curProject().url || "";
  $("srv").classList.remove("hidden");
  $("srv-url").focus();
  $("srv-url").select();
};
$("srv-cancel").onclick = () => $("srv").classList.add("hidden");
$("srv-save").onclick = () => {
  const u = $("srv-url").value.trim();
  if (!u) return;
  if (u === curProject().url) { $("srv").classList.add("hidden"); return; }
  $("srv").classList.add("hidden");
  act("relocate", [u], "Changing the server address…");
};
$("srv-url").onkeydown = e => {
  if (e.key === "Enter") $("srv-save").click();
  if (e.key === "Escape") $("srv-cancel").click();
};

$("b-forget").onclick = () => forget();
$("brk-forget").onclick = () => forget();
function forget() {
  if (!st) return;
  ask({
    title: "Remove “" + st.name + "” from the list?",
    lines: ["The files on disk are NOT deleted — the project just disappears " +
            "from APSVN.",
            { text: "If you still hold locks, nobody else will be able to edit " +
                    "those files until you connect to this project again.",
              warn: true }],
    ok: "Remove from list", danger: true,
  }).then(a => {
    if (!a.ok) return;
    gen++;
    act("forget_project", [st.pid], "Removing from the list…");
  });
}

$("brk-retry").onclick = async () => {
  busy(true, "Checking the folder…"); await refresh(); busy(false);
};
$("brk-where").onclick = async () => {
  const d = await api().pick_folder();
  if (!d) return;
  showSetup(true);
  $("s-url").value = (st && st.projects.find(p => p.id === st.pid) || {}).url || "";
  $("s-dir").value = d;
  $("s-name").value = st.name || "";
  $("s-msg").textContent = "Enter your user name and password — the project will pick up from the new folder.";
};

/* --- майстер підключення ---------------------------------------------- */

function showSetup(cancelable) {
  $("setup").classList.remove("hidden");
  $("main").classList.add("hidden");
  $("s-title").textContent = cancelable ? "New project" : "Connect to a project";
  $("s-cancel").classList.toggle("hidden", !cancelable);
  if (!cancelable && st && st.error) $("s-msg").textContent = st.error;
}

$("s-cancel").onclick = () => {
  $("setup").classList.add("hidden");
  $("main").classList.remove("hidden");
  $("s-msg").textContent = "";
};
$("s-pick").onclick = async () => {
  const d = await api().pick_folder();
  if (d) $("s-dir").value = d;
};
$("s-go").onclick = async () => {
  $("s-msg").textContent = "";
  busy(true, "Downloading the project. The first time can take a while — keep this window open.");
  try {
    await api().add_project($("s-url").value.trim(), $("s-dir").value.trim(),
                            $("s-user").value.trim(), $("s-pass").value,
                            $("s-name").value.trim());
    gen++;
    selected.clear();
    ["s-url", "s-dir", "s-user", "s-pass", "s-name"].forEach(i => $(i).value = "");
    $("setup").classList.add("hidden");
    await refresh();
  } catch (e) {
    $("s-msg").textContent = clean(e);
  }
  busy(false);
};

/* --- вкладки ---------------------------------------------------------- */

document.querySelectorAll(".tab").forEach(b => b.onclick = async () => {
  const t = b.dataset.tab;
  if (t === "browse") { showView("browse"); return openDir(brPath); }
  if (t === "history") { showView("log"); return loadLog(); }
  showView("files"); renderFiles();
});

/* --- історія проєкту -------------------------------------------------
   Дві панелі: ліворуч коміти, праворуч — що в обраному сталося.
   Перелік файлів тягнемо НА ВИМОГУ, коли коміт обрали: це 0.1 с і 300
   байтів на коміт, а одразу на всі сорок було б півмегабайта через міст
   між Python і вебвʼю заради одного, який справді відкриють. */
let logRows = [], logRev = null;
const revCache = {};              // ревізія -> список файлів, читаємо раз
let revPick = new Set();          // що позначено в правій панелі

// «2 years ago» — так час читається одним поглядом, а точну дату лишаємо
// в підказці й у правій панелі.
function ago(str) {
  const t = Date.parse((str || "").replace(" ", "T"));
  if (!t) return str || "";
  const sec = (Date.now() - t) / 1000;
  if (sec < 90) return "just now";
  const step = [[60, "minute"], [3600, "hour"], [86400, "day"],
                [604800, "week"], [2629800, "month"], [31557600, "year"]];
  let unit = "minute", div = 60;
  for (const [d, u] of step) if (sec >= d) { div = d; unit = u; }
  const n = Math.floor(sec / div);
  return n + " " + unit + (n === 1 ? "" : "s") + " ago";
}

async function loadLog() {
  const box = $("log");
  box.innerHTML = "<div class='empty'>Reading history…</div>";
  try { logRows = await api().get_log(); } catch (e) { logRows = []; }
  box.innerHTML = "";
  if (!logRows.length) {
    box.innerHTML = "<div class='empty'>No history yet</div>";
    $("hist-side").innerHTML =
      "<div class='br-empty'>Nothing has been submitted yet</div>";
    return;
  }
  for (const e of logRows) {
    const d = document.createElement("div");
    d.className = "le";
    d.dataset.rev = e.rev;
    const m = document.createElement("div");
    m.className = "m";
    m.textContent = e.msg || "(no note)";
    const meta = document.createElement("div");
    meta.className = "meta";
    meta.textContent = e.author + " · " + ago(e.date);
    meta.title = e.date;
    d.append(m, meta);
    d.onclick = () => pickCommit(e.rev);
    box.append(d);
  }
  pickCommit(logRows[0].rev);           // щось має бути показано одразу
}

function pickCommit(rev) {
  logRev = rev;
  revPick.clear();                // вибір належить комітові, не панелі
  document.querySelectorAll("#log .le").forEach(
    n => n.classList.toggle("on", n.dataset.rev === String(rev)));
  renderCommit();
}

async function renderCommit() {
  const rev = logRev;
  const side = $("hist-side");
  const e = logRows.find(x => String(x.rev) === String(rev));
  if (!e) { side.innerHTML = "<div class='br-empty'>Pick a commit</div>"; return; }

  side.innerHTML = "";
  const head = document.createElement("div");
  head.className = "ch-head";
  const msg = document.createElement("div");
  msg.className = "ch-msg";
  msg.textContent = e.msg || "(no note)";
  const who = document.createElement("div");
  who.className = "ch-who";
  who.textContent = e.author + " · " + e.date + " · commit " + e.rev;
  head.append(msg, who);
  side.append(head);

  const count = document.createElement("div");
  count.className = "ch-count";
  count.textContent = "Reading what changed…";
  side.append(count);
  const list = document.createElement("div");
  list.className = "ch-files";
  side.append(list);

  let d = revCache[rev];
  if (!d) {
    try { d = await api().revision_files(rev); }
    catch (err) { d = null; }
    if (d) revCache[rev] = d;
  }
  if (logRev !== rev) return;           // поки читали, обрали інший коміт
  if (!d) { count.textContent = "Could not read what changed"; return; }

  const n = d.total || 0;
  count.textContent = n === 1 ? "1 changed file" : n + " changed files";
  for (const f of d.files) {
    const row = document.createElement("div");
    row.className = "ch-f";
    const mark = document.createElement("span");
    mark.className = "ch-mark " + f.action;
    mark.textContent = { A: "+", M: "●", D: "−", R: "↻" }[f.action] || "●";
    mark.title = f.action_text;
    // Тека втрачає початок, імʼя файлу видно завжди. Альтернатива —
    // direction:rtl на весь рядок — коротша, але переставляє кінцеві
    // дужки й крапки в іменах на кшталт "render (final).png".
    const i = f.path.lastIndexOf("/");
    const nm = document.createElement("div");
    nm.className = "ch-p";
    nm.title = f.path;
    if (i > 0) {
      const dir = document.createElement("span");
      dir.className = "ch-dir";
      dir.textContent = f.path.slice(0, i + 1);
      nm.append(dir);
    }
    const base = document.createElement("span");
    base.className = "ch-name";
    base.textContent = i > 0 ? f.path.slice(i + 1) : f.path;
    nm.append(base);
    row.append(mark, nm);
    if (f.props_only) row.append(chip("settings only", ""));
    // Теку відкотити не можна: svn відновлює файли, а не дерева, і обіцяти
    // тут більше, ніж ми вміємо, гірше, ніж не пропонувати зовсім.
    if (f.kind !== "dir") {
      const cb = document.createElement("input");
      cb.type = "checkbox";
      cb.className = "ch-cb";
      cb.checked = revPick.has(f.path);
      cb.title = "pick this file to bring back";
      cb.onchange = () => {
        cb.checked ? revPick.add(f.path) : revPick.delete(f.path);
        syncRevBar();
      };
      row.prepend(cb);
    } else {
      const gap = document.createElement("span");
      gap.className = "ch-cb-gap";
      row.prepend(gap);
    }
    list.append(row);
  }
  if (d.truncated) {
    const w = document.createElement("div");
    w.className = "ch-more";
    w.textContent = "…showing the first " + d.files.length + " of " + n +
                    ". This looks like the commit that first filled the project.";
    list.append(w);
  }
  syncRevBar();
}

/* --- відкат просто з історії -------------------------------------------
   Смужка з'являється, лише коли є що позначати: порожня кнопка «повернути»
   під кожним комітом виглядала б як запрошення натиснути навмання. */
function syncRevBar() {
  const bar = $("ch-bar"), d = revCache[logRev];
  const pickable = d ? d.files.filter(f => f.kind !== "dir") : [];
  const n = revPick.size;
  bar.classList.toggle("hidden", !pickable.length);
  $("ch-all").checked = pickable.length > 0 &&
                        pickable.every(f => revPick.has(f.path));
  $("ch-count").textContent = n
    ? (n === 1 ? "1 file picked" : n + " files picked")
    : "pick files to bring back";
  $("ch-restore").disabled = !n;
  $("ch-restore").textContent = n > 1
    ? "↺ Bring back these " + n : "↺ Bring back";
}

$("ch-all").onchange = () => {
  const d = revCache[logRev];
  const pickable = d ? d.files.filter(f => f.kind !== "dir") : [];
  revPick.clear();
  if ($("ch-all").checked) for (const f of pickable) revPick.add(f.path);
  renderCommit();
};

$("ch-restore").onclick = async () => {
  const d = revCache[logRev], rev = logRev;
  if (!d || !revPick.size) return;
  const picked = d.files.filter(f => revPick.has(f.path));
  const gone = picked.filter(f => f.action === "D");
  const lines = ["Your files will become exactly what they were in that commit."];
  // Про видалені кажемо окремо: їх беремо з ПОПЕРЕДНЬОГО коміту, бо в цьому
  // їх уже немає. Людина має розуміти, що саме отримає.
  if (gone.length)
    lines.push((gone.length === 1 ? "One of them was deleted"
                                  : gone.length + " of them were deleted") +
               " in this commit, so it comes back as it was just before.");
  lines.push("A copy of what you have right now goes to “Safety copies” first.");
  lines.push("Nothing is sent to the server — you still have to press Submit " +
             "afterwards.");
  const a = await ask({
    title: picked.length === 1 ? "Bring this file back?"
                              : "Bring back " + picked.length + " files?",
    facts: picked.slice(0, 10).map(f => [f.path, f.action_text])
      .concat(picked.length > 10
        ? [["…and " + (picked.length - 10) + " more", ""]] : []),
    lines: lines,
    ok: "Bring them back", danger: true,
  });
  if (!a.ok) return;
  await act("restore_many", [rev, picked.map(
    f => ({ path: f.path, action: f.action }))], "Bringing files back…");
  revPick.clear();
  renderCommit();
};

/* --- опитування: наступне лише після завершення попереднього ----------- */

function loop() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    if ($("busy").classList.contains("hidden") &&
        $("setup").classList.contains("hidden") &&
        view !== "file" && view !== "browse") {
      try { await refresh(); } catch (e) { /* наступний оберт спробує ще */ }
    }
    loop();
  }, 10000);                          // локи чужих людей мають з’являтись швидко
}

window.addEventListener("pywebviewready", () => {
  refresh();
  loop();
  // тихо, один раз: якщо нового немає — художник про це навіть не дізнається
  setTimeout(() => checkUpdate(true), 3000);
});
