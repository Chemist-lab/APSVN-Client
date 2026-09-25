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
                    (line.bad ? " bad-line" : "") + (line.mono ? " mono" : "");
      d.textContent = line.text != null ? line.text : line;
      t.append(d);
    }

    // Картинки поруч — щоб вибирати, БАЧАЧИ: «твоя» і «колеги» в конфлікті.
    // Порожнє місце лишається підписаним, а не зникає: «картинки немає» —
    // теж відповідь, і без неї друга половина здавалася б зламаною.
    const imgs = $("m-imgs");
    imgs.innerHTML = "";
    const pics = (o.images || []).filter(Boolean);
    imgs.classList.toggle("hidden", !pics.some(([, src]) => src));
    for (const [label, src] of pics) {
      const f = document.createElement("figure");
      if (src) {
        const im = document.createElement("img");
        im.src = src; im.alt = "";
        f.append(im);
      } else {
        const ph = document.createElement("div");
        ph.className = "ph"; ph.textContent = "no picture";
        f.append(ph);
      }
      const c = document.createElement("figcaption");
      c.textContent = label;
      f.append(c);
      imgs.append(f);
    }

    const inp = $("m-input");
    inp.value = (o.input && o.input.value) || "";
    inp.placeholder = (o.input && o.input.placeholder) || "";
    inp.classList.toggle("hidden", !o.input);
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
      // факти першими — коли вони і є суть («що саме ти видаляєш»), а
      // рядки нижче лише пояснюють наслідки
      if (o.factsFirst) t.prepend(f); else t.append(f);
    }

    const chkWrap = $("m-chk-wrap"), chk = $("m-chk");
    chk.checked = false;
    chkWrap.classList.toggle("hidden", !o.remember);
    $("m-chk-t").textContent = o.remember || "";

    const ok = $("m-ok"), alt = $("m-alt"), cancel = $("m-cancel");
    ok.textContent = o.ok || "OK";
    ok.className = "primary" + (o.danger ? " bad" : "");
    cancel.textContent = o.cancel || "Cancel";
    // Вікно-пояснення (відмова сервера) питати нема про що — лише «ясно».
    cancel.classList.toggle("hidden", !!o.noCancel);
    alt.textContent = o.alt || "";
    alt.classList.toggle("hidden", !o.alt);

    const done = res => {
      $("modal").classList.add("hidden");
      document.removeEventListener("keydown", onKey, true);
      resolve(Object.assign({ ok: false, alt: false, remember: chk.checked,
                              text: inp.value.trim() }, res));
    };
    const onKey = e => {
      if (e.key === "Escape") { e.preventDefault(); done({}); }
      // У полі коментаря Enter — новий рядок; відправити — Ctrl+Enter
      if (e.key === "Enter" && (e.target !== inp || e.ctrlKey)) {
        e.preventDefault(); done({ ok: true });
      }
    };
    ok.onclick = () => done({ ok: true });
    alt.onclick = () => done({ alt: true });
    cancel.onclick = () => done({});
    $("modal").onclick = e => { if (e.target === $("modal")) done({}); };
    document.addEventListener("keydown", onKey, true);

    $("modal").classList.remove("hidden");
    (o.input ? inp : ok).focus();
  });
}

/* Відмова сервера за правилом студії (RuleError) — вікном, а не тостом.
   Це не збій: сервер пояснює, чий файл і до кого йти, і пояснення на кілька
   рядків за дев'ять секунд тосту не прочитати. Перший рядок тексту — це
   заголовок («These files are assigned to someone else»), рядки з відступом
   — шляхи й люди, решта — порада. */
function fail(e, ms) {
  if (e && e.name === "RuleError") {
    const lines = clean(e).split("\n");
    const title = (lines.shift() || "The server did not allow this")
      .replace(/:\s*$/, "");
    return ask({
      title: title,
      lines: lines.filter(l => l.trim()).map(
        l => /^\s/.test(l) ? { text: l.trim(), mono: true } : l),
      ok: "OK", noCancel: true,
    });
  }
  toast(clean(e), ms || 9000);
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
  // Інший проєкт — інший сервер, інші задачі, інші картинки: шляхи в двох
  // проєктах можуть збігатися, а файли за ними — ні. Одне правило тут
  // замість скидання в кожному місці, де проєкт може змінитися (вибір,
  // додавання, «прибрати зі списку»).
  if (s.pid !== srvPid) {
    srvPid = s.pid;
    srvInfo = null; tasksData = null; tasksSigLast = null;
    taskSel = null; taskDone = null;
    THUMBS.clear();
    renderTaskBadge();
    resetExplorer();
    if (s.configured) initServer();
  }

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
  // Провідник показує проєкт станом на останню синхронізацію — отже, щойно
  // вона оновилась, оновлюється й поточна тека. Локально, без мережі, а
  // незмінені рядки лишаються тими самими вузлами.
  if (view === "browse") refreshDir();
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
  for (const id of ["tab-files", "tab-history", "tab-browse", "tab-tasks",
                    "filehist"])
    $(id).classList.add("hidden");
  $("tab-broken").classList.remove("hidden");
  $("brk-title").textContent = s.broken;
  $("brk-path").textContent = s.wc || "";
}

// внутрішні режими -> кнопки вкладок. Історія ОДНОГО файлу лишає підсвіченими
// «Файли», бо вона відкривається саме звідти.
const TAB_OF = { files: "files", file: "files", log: "history",
                 browse: "browse", tasks: "tasks" };

function showView(v) {
  view = v;
  $("tab-broken").classList.add("hidden");
  $("filehist").classList.toggle("hidden", v !== "file");
  $("tab-files").classList.toggle("hidden", v !== "files");
  $("tab-history").classList.toggle("hidden", v !== "log");
  $("tab-browse").classList.toggle("hidden", v !== "browse");
  $("tab-tasks").classList.toggle("hidden", v !== "tasks");
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

// Перенос — це ДВА записи svn: нове місце (moved here) і старе (moved away).
// Людина робила одну дію, тож і бачить один рядок — нове місце; старе їде
// разом із ним при здачі (do_commit додає його сам). Винятки — конфлікт на
// старому місці: його треба бачити, бо там і вирішують.
const hiddenHalf = f => !!(f.moved_to && f.status !== "conflicted");

// Нове місце не здається, поки старе в конфлікті: svn відмовить.
function blockedMove(f, files) {
  return !!(f.moved_from && files.some(
    x => x.path === f.moved_from && x.status === "conflicted"));
}

function renderFiles() {
  const box = $("files");
  const all = (st && st.files) || [];
  const files = all.filter(f => !hiddenHalf(f));

  // прибираємо з вибору те, чого вже немає або що не можна здавати
  const live = new Set(files
    .filter(f => f.status !== "conflicted" && !(f.lock_owner && !f.lock_mine)
                 && !blockedMove(f, all))
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
                                ICONS.get(extOf(f.path, f.dir)) ? 1 : 0,
                                taskSig(f.path)]),
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
    const blocked = f.status === "conflicted" || !!(f.lock_owner && !f.lock_mine)
                    || blockedMove(f, (st && st.files) || []);
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
    if (f.moved_from && f.status !== "conflicted") {
      const from = chip("from " + (parentOf(f.moved_from) || "the project root") + "/",
                        "moved");
      from.title = "moved from " + f.moved_from + " — it goes to the server as a move, " +
                   "with its history";
      row.append(from);
    }
    if (f.remote_change) row.append(chip("newer on the server", "remote"));
    const tc = taskChip(f.path);
    if (tc) row.append(tc);
    if (f.dir) {
      row.append(chip(f.n_files + (f.counted_all === false ? "+" : "") +
                      (f.n_files === 1 ? " file" : " files") +
                      (f.bytes ? " · " + fmtSize(f.bytes) : "")));
    }

    if (f.status === "conflicted" && f.conflict_kind === "moved") {
      // Ти переніс файл, а колега тим часом його змінив. «Лишити мій
      // перенос» тут безпечне: зміна колеги їде у файл на новому місці
      // (svn resolve --accept mine-conflict, перевірено дослідом). Звичне
      // «keep my file» (--accept working) її б мовчки викинуло.
      const dest = f.moved_to || "";
      row.append(mini("keep my move", "", () => {
        ask({
          title: "Keep your move?",
          lines: ["You moved “" + baseOf(f.path) + "” to “" +
                  (parentOf(dest) || "the project root") + "”, and meanwhile a " +
                  "colleague changed it.",
                  "Their change goes into the file at its new place — nothing of " +
                  "theirs is lost. You still have to submit the move."],
          ok: "Keep my move",
        }).then(a => {
          if (a.ok) act("do_resolve", [[f.path], true, "mine"],
                        "Bringing their change to the new place…");
        });
      }));
      row.append(mini("put it back", "danger", () => {
        ask({
          title: "Undo your move?",
          lines: ["“" + baseOf(f.path) + "” goes back to “" +
                  (parentOf(f.path) || "the project root") + "” — with your " +
                  "colleague’s change.",
                  "Your copy from the new place goes to “Safety copies” first."],
          ok: "Put it back", danger: true,
        }).then(a => {
          if (a.ok) act("do_resolve", [[f.path], false, "theirs"],
                        "Putting it back…");
        });
      }));
    } else if (f.status === "conflicted") {
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

      row.append(mini(moved ? "keep my file" : "keep my version", "", async () => {
        const pics = await conflictPics(f, k);
        ask({
          title: moved ? "Keep your file?" : "Keep your version?",
          images: pics,
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
                      "take my colleague’s version", "danger", async () => {
        const pics = await conflictPics(f, k);
        ask({
          title: moved ? "Go with the team’s version?"
                       : "Take your colleague’s version?",
          images: pics,
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
      if (f.moved_from && !blockedMove(f, (st && st.files) || [])) {
        // Повернення — справжнє «скасувати»: svn упізнає його, і статус
        // стає чистим; зміни, зроблені після переносу, лишаються у файлі.
        // Коли старе місце в конфлікті, повертати нікуди — вирішують там.
        row.append(mini("↶ Move back", "", () =>
          act("move_back", [f.path], "Moving it back…")));
      }
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
      // Теку не займають — займають файли. І лише ті, що вже є на сервері:
      // новий чи щойно перенесений файл svn зайняти не дасть (його там ще
      // немає), тож кнопка лише відмовляла б.
      if (!f.dir && f.status !== "added" && f.status !== "unversioned") {
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

  // «і відправити на перевірку» — лише коли серед вибраного справді є файл
  // твоєї задачі, яку ще можна туди відправити. Інакше галочки немає зовсім:
  // порожній вимикач під рукою щодня лише збиває.
  const rt = reviewTasks();
  $("c-review-l").classList.toggle("hidden", !rt.length);
  if (!rt.length) $("c-review").checked = false;
  $("c-review-t").textContent = rt.length === 1
    ? "send “" + rt[0].name + "” to review"
    : "send " + rt.length + " tasks to review";
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
  // «Ця версія — у тебе». Для незміненого файлу svn знає це сам: це
  // найновіша з історії, не новіша за ревізію файлу в копії. Для зміненого —
  // див. markDiskVersion нижче.
  let have = null;
  if (!hist.dirty && hist.base != null)
    have = (hist.rows.find(r => Number(r.rev) <= hist.base) || {}).rev || null;
  const ACT = { A: "added", M: "changed", D: "deleted", R: "replaced" };
  const withPics = srvOn() && PREVIEWABLE.test(hist.path);
  for (const r of hist.rows) {
    const d = document.createElement("div"); d.className = "hr";
    d.dataset.rev = r.rev;
    if (withPics) {
      const th = document.createElement("div");
      th.className = "hr-thumb";
      d.append(th);
    }
    const body = document.createElement("div"); body.className = "hr-main";
    const head = document.createElement("div"); head.className = "meta";
    head.textContent = "commit " + r.rev + " · " + r.author + " · " + r.date +
      (ACT[r.action] ? " · " + ACT[r.action] : "");
    if (String(r.rev) === String(have)) {
      head.append(" ", chip("you have this version", "have"));
    }
    const m = document.createElement("div"); m.className = "m";
    m.textContent = r.msg || "(no note)";
    body.append(head, m);
    if (r.renamed_from) {
      const rn = document.createElement("div"); rn.className = "dim";
      rn.textContent = "back then it was called “" + r.renamed_from + "”";
      body.append(rn);
    }
    const bar = document.createElement("div"); bar.className = "hr-bar";
    bar.append(mini("👁 Save a copy…", "", () => saveAs(r.rev)));
    const rb = mini("⟲ Bring back this version", "warn", () => restore(r));
    rb.disabled = !!(hist.dirty || hist.locked_by);
    bar.append(rb);
    body.append(bar);
    d.append(body);
    box.append(d);
  }
  if (withPics || hist.dirty) versionPics(hist.path);
}

/* Картинки версій — із сервера, одним запитом на весь файл: він сам іде
   крізь перейменування і віддає по картинці на кожен різний вміст. Коли
   відповідь доїхала, людина могла вже відкрити інший файл — тоді мовчимо. */
async function versionPics(path) {
  let v = null;
  try { v = await api().file_versions(path); } catch (e) { v = null; }
  if (!hist || hist.path !== path || view !== "file" || !v || !v.ok) return;
  for (const row of document.querySelectorAll("#fh-rows .hr")) {
    const got = v.versions[row.dataset.rev];
    const th = row.querySelector(".hr-thumb");
    if (!th) continue;
    if (got && got.preview) {
      const im = document.createElement("img");
      im.src = got.preview; im.alt = "";
      th.replaceChildren(im);
    } else if (got && got.state === "pending") {
      th.textContent = "preparing…";
      th.title = "the server has not made a picture of this version yet";
    }
  }
  if (hist.dirty) markDiskVersion(path);
}

/* Файл змінено, тож svn не скаже, котра це версія. Але вміст може
   збігатися з однією з них — скажімо, людина щойно повернула стару й ще не
   здала. Сервер дає SHA-1 кожної версії; порахувати свою — нічого не качаючи.
   Великий файл читається секунди, тому це окремий крок, а не частина відкриття. */
async function markDiskVersion(path) {
  let w = null;
  try { w = await api().which_version(path); } catch (e) { w = null; }
  if (!hist || hist.path !== path || view !== "file" || !w || !w.rev) return;
  const row = document.querySelector("#fh-rows .hr[data-rev='" + w.rev + "']");
  const head = row && row.querySelector(".meta");
  if (head) head.append(" ", chip("your file on disk is this version — not submitted", "have"));
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
      .then(m => { busy(false); toast(m, 10000); })
      .catch(e => { busy(false); fail(e, 10000); })
      .then(() => { showView("files"); return refresh(); });
  });
}

/* --- провідник проєкту --------------------------------------------------
   Тека приходить БЕЗ мережі (див. explorer.py): диск + локальний svn +
   остання синхронізація. Тому навігація миттєва, а перемальовування —
   ключоване, як у списку змін: рядок із тими самими даними переживає
   оновлення тим самим вузлом, і нічого не блимає. Уже бачену теку показуємо
   з пам'яті одразу, а свіжу відповідь накладаємо поверх, коли приїде. */

let brPath = "", brSel = null;
let brDir = null;                 // остання намальована тека
let brPainted = null;             // яку теку малювали — щоб знати, чи гортати вгору
const brCache = new Map();        // тека -> її останній вміст
let brNav = 0;                    // номер запиту: запізнілі відповіді — за борт
const brBack = [], brFwd = [];    // назад / вперед, як у будь-якому провіднику
const brPick = new Set();         // вибрані рядки (Ctrl, Shift)
let brAnchor = null;              // від чого рахувати Shift-діапазон
let brSelSig = null;              // з якими даними малювали бічну панель
// дерево: які теки розгорнуті і що всередині кожної (кешуємо, бо той
// самий browse уже приніс список підтек — другий запит зайвий)
const treeOpen = new Set([""]);
let treeKids = {};

function resetExplorer() {
  brPath = ""; brSel = null; brDir = null; brPainted = null; brSelSig = null;
  brCache.clear(); brBack.length = 0; brFwd.length = 0;
  brPick.clear(); brAnchor = null;
  treeKids = {}; treeOpen.clear(); treeOpen.add("");
}

const brEntry = p => (brDir && brDir.entries.find(e => e.path === p)) || null;
const parentOf = p => p.includes("/") ? p.slice(0, p.lastIndexOf("/")) : "";
const baseOf = p => p.slice(p.lastIndexOf("/") + 1);

async function openDir(path, how) {
  how = how || {};
  const mine = ++brNav;
  const moving = path !== brPath || !brDir;
  if (moving && brDir && !how.history) {
    brBack.push(brPath);
    brFwd.length = 0;
  }
  if (moving) {
    brPath = path;
    brPick.clear(); brSel = null; brAnchor = null; brSelSig = null;
    sideEmpty();
    const cached = brCache.get(path);
    if (cached) paintDir(cached);            // миттєво — з пам'яті
    else $("br-list").classList.add("loading");
  }
  let d;
  try {
    d = await api().browse(path);
  } catch (e) {
    if (mine !== brNav) return;
    $("br-list").classList.remove("loading");
    brCache.delete(path);
    // Теки не стало (перенесли, видалили) — не лишаємо людину в порожнечі,
    // а піднімаємося до того, що існує.
    if (path) {
      toast(clean(e), 6000);
      return openDir(parentOf(path), { history: true });
    }
    return toast(clean(e), 8000);
  }
  if (mine !== brNav) return;                // людина вже відкрила іншу
  $("br-list").classList.remove("loading");
  brCache.set(d.path, d);
  paintDir(d);
}

// Оновити поточну теку на місці: після синхронізації, дії, приїзду іконок.
function refreshDir() {
  if (view === "browse" && brDir) return openDir(brPath, { history: true });
}

function paintDir(d) {
  brDir = d;
  treeKids[d.path] = d.entries.filter(e => e.kind === "dir" && !e.link);
  let acc = "";
  treeOpen.add("");
  for (const part of (d.path ? d.path.split("/") : [])) {
    acc = acc ? acc + "/" + part : part;
    treeOpen.add(acc);
  }
  renderCrumbs(d);
  renderDir(d);
  renderTree();
  syncNav();
  if (brPainted !== d.path) $("br-list").scrollTop = 0;   // нова тека — з початку
  brPainted = d.path;
  // Вибране могло змінитися (лок узяли, файл зник). Бічну панель
  // перемальовуємо лише тоді — не щоразу, інакше вона блимала б щоопитування.
  for (const p of [...brPick]) if (!brEntry(p)) brPick.delete(p);
  if (brSel && !brEntry(brSel)) brSel = [...brPick].pop() || null;
  if (brPick.size > 1) renderMulti();
  else if (!brSel) { if (brSelSig) { brSelSig = null; sideEmpty(); } }
  else if (JSON.stringify(brEntry(brSel)) !== brSelSig) showSide(brEntry(brSel));
  syncPick();
}

$("br-back").onclick = () => goBack();
$("br-fwd").onclick = () => goFwd();
$("br-up").onclick = () => goUp();

function syncNav() {
  $("br-back").disabled = !brBack.length;
  $("br-fwd").disabled = !brFwd.length;
  $("br-up").disabled = !brDir || brDir.parent === null;
}

function goBack() {
  if (!brBack.length) return;
  brFwd.push(brPath);
  openDir(brBack.pop(), { history: true });
}
function goFwd() {
  if (!brFwd.length) return;
  brBack.push(brPath);
  openDir(brFwd.pop(), { history: true });
}
function goUp() {
  if (brDir && brDir.parent !== null) openDir(brDir.parent);
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
      brCache.set(d.path, d);
      treeKids[path] = d.entries.filter(e => e.kind === "dir" && !e.link);
    } catch (e) {
      treeOpen.delete(path);
      renderTree();
      return toast(clean(e), 8000);
    }
  }
  renderTree();
}

function treeRow(item, depth) {
  const path = item ? item.path : "";
  const open = treeOpen.has(path);
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
  lb.textContent = item ? item.name : ((st && st.name) || "project");
  row.append(ic, lb);
  if (item && item.new_inside) {
    const d = document.createElement("span");
    d.className = "dot"; d.title = "somebody submitted something in here";
    row.append(d);
  }
  if (item && item.mine_inside) {
    const d = document.createElement("span");
    d.className = "dot mine"; d.title = "you have unsubmitted work in here";
    row.append(d);
  }
  row.onclick = () => { if (path !== brPath) openDir(path); };
  if (!(item && item.nested)) dropTarget(row, path);
  return row;
}

// Ключоване, як і список: розгорнули теку — додалися її рядки, решта дерева
// лишилася тими самими вузлами.
function renderTree() {
  const items = [];
  const walk = (item, depth) => {
    const path = item ? item.path : "";
    const open = treeOpen.has(path), kids = treeKids[path];
    items.push(["t:" + path,
                JSON.stringify([item ? [item.name, item.new_inside, item.mine_inside,
                                        item.nested] : (st && st.name),
                                depth, open, path === brPath]),
                () => treeRow(item, depth)]);
    if (!open) return;
    if (!kids) {
      items.push(["w:" + path, String(depth), () => {
        const w = document.createElement("div");
        w.className = "tn"; w.style.paddingLeft = (6 + (depth + 1) * 13) + "px";
        w.innerHTML = "<span class='tw empty'></span><span class='tl dim'>reading…</span>";
        return w;
      }]);
      return;
    }
    for (const k of kids) walk(k, depth + 1);
  };
  walk(null, 0);
  reconcile($("br-tree"), items);
}

function renderCrumbs(d) {
  const box = $("crumbs");
  box.innerHTML = "";
  const parts = d.path ? d.path.split("/") : [];
  const mk = (label, target, last) => {
    const b = document.createElement("button");
    b.className = "crumb" + (last ? " last" : "");
    b.textContent = label;
    if (!last) {
      b.onclick = () => openDir(target);
      dropTarget(b, target);                 // тягнути на рівень вище — сюди
    }
    return b;
  };
  box.append(mk((st && st.name) || "project", "", parts.length === 0));
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
  const box = $("br-list");
  const items = [];
  if (d.parent !== null) items.push(["up", "up:" + d.parent, () => upRow(d.parent)]);
  if (!d.entries.length) {
    items.push(["empty", "empty", () => {
      const e = document.createElement("div");
      e.className = "empty"; e.textContent = "This folder is empty";
      return e;
    }]);
  }
  for (const it of d.entries) {
    items.push(["e:" + it.path,
                JSON.stringify([it, ICONS.get(extOf(it.name, it.kind === "dir")) ? 1 : 0,
                                taskSig(it.path), nativeDrag]),
                () => entryRow(it)]);
  }
  reconcile(box, items);
  syncPick();
  wantIcons(d.entries.filter(e => e.kind !== "dir").map(e => e.name),
            d.entries.some(e => e.kind === "dir"));
}

function upRow(parent) {
  const up = document.createElement("div");
  up.className = "e dir up";
  up.innerHTML = "<div class='ico'>↰</div>";
  const nm = document.createElement("div");
  nm.className = "nm"; nm.textContent = "..";
  up.append(nm);
  up.onclick = () => openDir(parent);
  dropTarget(up, parent);
  return up;
}

// Вибір малюємо класами, а не перебудовою: рядки ті самі, змінилась лише
// підсвітка — нема чого знищувати й будувати наново.
function syncPick() {
  for (const n of $("br-list").children) {
    const k = n.dataset.k || "";
    if (!k.startsWith("e:")) continue;
    const p = k.slice(2);
    n.classList.toggle("on", brPick.has(p));
    n.classList.toggle("focus", p === brSel && brPick.size > 1);
  }
}

function entryRow(it) {
  const row = document.createElement("div");
  row.className = "e " + it.kind + (it.on_disk ? "" : " ghost-row");
  const isDir = it.kind === "dir";
  const plain = !it.nested && !it.link;      // справжня тека проєкту

  // Ярлик лишається ярликом: система дала б іконку цілі, а тут важливо саме
  // те, що це не справжня тека проєкту.
  row.append(it.link ? iconEl("ico", "", false, "🔗")
                     : iconEl("ico", it.name, isDir,
                              isDir ? "📁" : (it.binary ? "🎬" : "📄")));

  const nm = document.createElement("div");
  nm.className = "nm"; nm.textContent = it.name; nm.title = it.path;
  if (isDir && plain) {
    nm.onclick = ev => {
      if (!ev.ctrlKey && !ev.shiftKey && !ev.metaKey) openDir(it.path);
    };
  }
  row.append(nm);

  row.addEventListener("mousedown", ev => rowDown(ev, it));
  row.addEventListener("mouseup", ev => rowUp(ev, it));
  row.ondblclick = () => {
    if (isDir) { if (plain) openDir(it.path); }
    else if (it.openable && it.on_disk) openIt(it);
  };
  row.oncontextmenu = ev => rowMenu(ev, it);
  // Без нативного перетягування (не Windows) тягнемо засобами сторінки —
  // лише між теками. На Windows рядок НЕ draggable: інакше вебвʼю почав би
  // власне перетягування, яке нічого не вміє віддати Blender.
  if (nativeDrag === false && it.on_disk) {
    row.draggable = true;
    row.ondragstart = ev => pageDragStart(ev, it);
    row.ondragend = pageDragEnd;
  }
  if (isDir && plain) dropTarget(row, it.path);

  if (isDir && plain) {
    // Теки svn не блокує — блокуємо все, що в них. Числа беремо з сервера
    // ПЕРЕД дією, щоб у діалозі стояла правда, а не обіцянка.
    row.append(still(mini("🔓 lock folder", "", ev => {
      ev.stopPropagation();
      folderLock(it);
    })));
  }
  if (it.nested) row.append(chip("separate project", ""));
  if (it.link) row.append(chip("shortcut", ""));
  if (it.new_inside) row.append(chip("new inside", "remote"));
  if (it.status && !["normal", "none", "unversioned"].includes(it.status))
    row.append(chip(it.status_text, it.status));
  if (it.status === "unversioned" && it.on_disk) row.append(chip("new", "unversioned"));
  if (it.remote_change && it.on_disk) row.append(chip("newer on the server", "remote"));
  if (!it.on_disk) row.append(chip("not downloaded yet", "remote"));
  if (plain) {
    const tc = taskChip(it.path);
    if (tc) row.append(still(tc));
  }

  if (!isDir) {
    const lb = document.createElement("button");
    lb.className = "lockbtn";
    if (it.lock_stale) {
      lb.classList.add("stale"); lb.textContent = "lock removed";
      lb.onclick = ev => { ev.stopPropagation(); act("do_update", [], "Getting latest…"); };
    } else if (it.lock_mine) {
      lb.classList.add("mine"); lb.textContent = "🔒 mine";
      lb.onclick = ev => {
        ev.stopPropagation();
        act("do_unlock", [[it.path]], "Releasing…");
      };
    } else if (it.lock_owner) {
      lb.classList.add("other"); lb.textContent = "🔒 " + it.lock_owner;
      lb.disabled = true;
      lb.title = "locked until your colleague submits their work";
    } else if (it.on_disk && !["unversioned", "added"].includes(it.status)) {
      lb.textContent = "🔓 lock";
      lb.onclick = ev => {
        ev.stopPropagation();
        act("do_lock", [[it.path]], "Locking…");
      };
    }
    // Порожню кнопку не малюємо: нескачаному чи новому файлу займати нічого,
    // а пуста «пігулка» в рядку виглядала як поламка.
    if (lb.textContent) row.append(still(lb));
  }

  const sz = document.createElement("div");
  sz.className = "sz"; sz.textContent = it.size == null ? "" : fmtSize(it.size);
  const dt = document.createElement("div");
  dt.className = "dt"; dt.textContent = it.mtime || "";
  row.append(sz, dt);
  return row;
}

// Кнопка в рядку — це кнопка, а не початок вибору чи перетягування.
function still(el) {
  el.addEventListener("mousedown", ev => ev.stopPropagation());
  return el;
}

/* --- вибір: клік, Ctrl, Shift — як у файловому менеджері ------------------ */
let dragCand = null;              // натиснули на рядок — може, зараз потягнуть

function rowDown(ev, it) {
  if (ev.button !== 0) return;
  const p = it.path;
  if (ev.ctrlKey || ev.metaKey) {
    if (brPick.has(p)) brPick.delete(p); else brPick.add(p);
    brAnchor = p;
    brSel = brPick.has(p) ? p : ([...brPick].pop() || null);
    syncPick();
    return showSelection();
  }
  if (ev.shiftKey && brAnchor && brDir) {
    const order = brDir.entries.map(e => e.path);
    const a = order.indexOf(brAnchor), b = order.indexOf(p);
    if (a >= 0 && b >= 0) {
      brPick.clear();
      for (let i = Math.min(a, b); i <= Math.max(a, b); i++) brPick.add(order[i]);
      brSel = p;
      syncPick();
      return showSelection();
    }
  }
  if (!brPick.has(p)) {
    brPick.clear(); brPick.add(p); brAnchor = p; brSel = p;
    syncPick();
    showSelection();
  } else {
    brSel = p;                    // група лишається — її можна потягнути разом
    syncPick();
  }
  dragCand = { x: ev.clientX, y: ev.clientY, path: p, group: brPick.size > 1 };
}

function rowUp(ev, it) {
  // Клік без перетягування по файлу з уже вибраної групи — лишити лише його.
  if (dragCand && dragCand.group && dragCand.path === it.path &&
      !(ev.ctrlKey || ev.shiftKey || ev.metaKey)) {
    brPick.clear(); brPick.add(it.path); brAnchor = it.path; brSel = it.path;
    syncPick();
    showSelection();
  }
  dragCand = null;
}

function showSelection() {
  if (brPick.size > 1) return renderMulti();
  const it = brSel && brEntry(brSel);
  if (it) showSide(it); else { brSelSig = null; sideEmpty(); }
}

// Вибране, що є на диску, — у порядку списку, а не кліків.
function pickedOnDisk() {
  return ((brDir && brDir.entries) || [])
    .filter(e => brPick.has(e.path) && e.on_disk).map(e => e.path);
}

async function copyPaths(paths) {
  try { toast(await api().copy_paths(paths), 4000); }
  catch (e) { fail(e); }
}

/* --- перетягування ------------------------------------------------------
   Один жест на все. На Windows тягнуться СПРАВЖНІ файли (як із Провідника):
   кинув у Blender — він їх відкриває чи чіпляє, кинув у Провідник —
   копіює, кинув на теку тут — APSVN переносить через svn move. Назовні
   файл лише копіюється, ніколи не забирається: див. desktop._drag_on_ui.
   Поза Windows тягнемо засобами сторінки — лише між теками. */
let nativeDrag = null;            // null — ще не знаємо; true — Windows
let dragging = null;              // { paths } — що тягнуть просто зараз
let dropTo = null;                // на яку теку кинули

document.addEventListener("mousemove", ev => {
  if (!dragCand || !(ev.buttons & 1) || nativeDrag !== true) return;
  if (Math.abs(ev.clientX - dragCand.x) + Math.abs(ev.clientY - dragCand.y) < 6) return;
  dragCand = null;
  const paths = pickedOnDisk();
  if (paths.length) nativeDragStart(paths);
});
document.addEventListener("mouseup", () => { dragCand = null; });

async function nativeDragStart(paths) {
  dragging = { paths: paths };
  dropTo = null;
  document.body.classList.add("dragging-files");
  let r = null;
  try { r = await api().drag_out(paths); } catch (e) { r = "error"; }
  document.body.classList.remove("dragging-files");
  clearDropMarks();
  if (r === "unsupported") { nativeDrag = false; if (brDir) renderDir(brDir); }
  finishDrag();
}

function pageDragStart(ev, it) {
  const paths = brPick.has(it.path) ? pickedOnDisk() : [it.path];
  dragging = { paths: paths };
  dropTo = null;
  ev.dataTransfer.effectAllowed = "move";
  ev.dataTransfer.setData("text/plain", paths.join("\n"));
  document.body.classList.add("dragging-files");
}

function pageDragEnd() {
  document.body.classList.remove("dragging-files");
  clearDropMarks();
  if (dragging && dropTo === null) dragging = null;   // кинули в нікуди
}

function finishDrag() {
  const d = dragging, to = dropTo;
  dragging = null; dropTo = null;
  if (d && to !== null) moveInto(d.paths, to);
}

// Чи має сенс кинути сюди: не в саму себе, не в свою ж підтеку, і хоч
// щось справді має переїхати (не з цієї ж теки).
function canDropInto(folder) {
  if (!dragging) return false;
  let any = false;
  for (const p of dragging.paths) {
    if (folder === p || folder.startsWith(p + "/")) return false;
    if (parentOf(p) !== folder) any = true;
  }
  return any;
}

function clearDropMarks() {
  document.querySelectorAll(".drop-on").forEach(n => n.classList.remove("drop-on"));
}

function dropTarget(el, folder) {
  const over = ev => {
    if (!canDropInto(folder)) return;        // документ нижче відмовить сам
    ev.preventDefault();
    ev.stopPropagation();
    // Під час нативного перетягування дозволено лише «копію» (щоб Провідник
    // не забрав файл із копії), тож і тут кажемо «copy» — інакше кинути не
    // дадуть. Що саме станеться — перенос — пише підсвітка теки.
    ev.dataTransfer.dropEffect = nativeDrag ? "copy" : "move";
    if (!el.classList.contains("drop-on")) {
      clearDropMarks();
      el.classList.add("drop-on");
      el.dataset.drop = "move here";
    }
  };
  el.addEventListener("dragenter", over);
  el.addEventListener("dragover", over);
  el.addEventListener("dragleave", ev => {
    if (!el.contains(ev.relatedTarget)) el.classList.remove("drop-on");
  });
  el.addEventListener("drop", ev => {
    if (!canDropInto(folder)) return;
    ev.preventDefault();
    ev.stopPropagation();
    clearDropMarks();
    dropTo = folder;
    if (!nativeDrag) finishDrag();           // жест сторінки вже завершився
  });
}

// Кинуте туди, де приймати нічого — не відкривати файл у вікні замість
// APSVN. Без цього файл, кинутий з Провідника у вікно, підмінив би собою
// весь інтерфейс: вебвʼю просто відкриває кинуте.
document.addEventListener("dragover", ev => {
  ev.preventDefault();
  ev.dataTransfer.dropEffect = "none";
});
document.addEventListener("drop", ev => ev.preventDefault());

/* Перенос у теку. Питаємо лише тоді, коли є що сказати: тека (їде все, що в
   ній), сцени, які посилаються на файл, чужа задача. Звичайний перенос файлу
   — одразу: у «Changes» його видно, і «↶ Move back» повертає як було. */
async function moveInto(paths, folder) {
  const dest = folder ? baseOf(folder) : ((st && st.name) || "the project root");
  const dirs = paths.filter(p => (brEntry(p) || {}).kind === "dir");
  const lines = [];
  if (dirs.length)
    lines.push(dirs.length === 1 ? "Everything inside the folder goes with it."
                                 : "Everything inside those folders goes with them.");
  const theirs = [];
  for (const p of paths) {
    const t = tasksFor(p).find(x => !x.mine && x.status !== "done" && x.assignees.length);
    if (t) theirs.push(baseOf(p) + " — " + t.assignees.join(", "));
  }
  if (theirs.length)
    lines.push({ text: "Assigned to someone else: " + theirs.join("; ") +
                 ". If the project uses soft locks, the server will not accept " +
                 "this move from you.", warn: true });
  let ub = {};
  const files = paths.filter(p => !dirs.includes(p));
  if (files.length && srvOn()) {
    try { ub = await api().used_by_many(files); } catch (e) { ub = {}; }
  }
  const scenes = [...new Set(Object.values(ub).flat())];
  if (scenes.length) {
    lines.push({ text: "These scenes point at it and will open without it " +
                       "until they are pointed at the new place:", warn: true });
    for (const s of scenes.slice(0, 6)) lines.push({ text: s, mono: true });
    if (scenes.length > 6) lines.push("…and " + (scenes.length - 6) + " more");
  }
  if (lines.length) {
    lines.push("Nothing changes on the server until you submit it in “Changes”.");
    const a = await ask({
      title: "Move " + (paths.length === 1 ? "“" + baseOf(paths[0]) + "”"
                                           : paths.length + " items") +
             " to “" + dest + "”?",
      lines: lines,
      ok: "Move",
      danger: !!(scenes.length || theirs.length),
    });
    if (!a.ok) return;
  }
  await act("move_items", [paths, folder], "Moving…");
  // вміст обох тек і гілка дерева змінилися — пам'ять про них застаріла
  brCache.delete(folder);
  for (const p of paths) brCache.delete(p);
  delete treeKids[folder];
  if (treeOpen.has(folder)) {
    api().browse(folder).then(d => {
      brCache.set(d.path, d);
      treeKids[folder] = d.entries.filter(e => e.kind === "dir" && !e.link);
      renderTree();
    }).catch(() => {});
  }
  refreshDir();
}

/* --- контекстне меню ------------------------------------------------------ */
function ctxMenu(x, y, items) {
  const m = $("ctx");
  m.innerHTML = "";
  for (const [label, fn, cls] of items) {
    if (!label) {
      const s = document.createElement("div");
      s.className = "menu-sep";
      m.append(s);
      continue;
    }
    const b = document.createElement("button");
    b.className = "menu-item" + (cls ? " " + cls : "");
    b.textContent = label;
    b.onclick = ev => { ev.stopPropagation(); ctxClose(); fn(); };
    m.append(b);
  }
  m.classList.remove("hidden");
  // не вилазити за край вікна
  const r = m.getBoundingClientRect();
  m.style.left = Math.max(4, Math.min(x, innerWidth - r.width - 8)) + "px";
  m.style.top = Math.max(4, Math.min(y, innerHeight - r.height - 8)) + "px";
}

function ctxClose() { $("ctx").classList.add("hidden"); }

document.addEventListener("mousedown", ev => {
  if (!$("ctx").contains(ev.target)) ctxClose();
}, true);
document.addEventListener("keydown", ev => {
  if (ev.key === "Escape" && !$("ctx").classList.contains("hidden")) {
    ev.stopPropagation();
    ctxClose();
  }
}, true);

function rowMenu(ev, it) {
  ev.preventDefault();
  if (!brPick.has(it.path)) {
    brPick.clear(); brPick.add(it.path); brAnchor = it.path; brSel = it.path;
    syncPick();
    showSelection();
  }
  const paths = [...brPick];
  const web = () => api().open_web("file", it.path).catch(e => fail(e));
  const items = [];
  if (paths.length > 1) {
    items.push(["📋 Copy " + paths.length + " paths", () => copyPaths(paths)]);
  } else if (it.kind === "dir") {
    const plain = !it.nested && !it.link;
    if (plain) items.push(["📂 Open", () => openDir(it.path)]);
    items.push(["🗂 Show in folder", () => api().reveal(it.path)]);
    items.push(["📋 Copy path", () => copyPaths([it.path])]);
    if (plain) {
      items.push(["", null]);
      items.push(["🔓 Lock everything inside", () => folderLock(it)]);
    }
    if (srvOn() && plain) items.push(["🌐 On the studio website", web]);
  } else {
    if (it.openable && it.on_disk)
      items.push([it.binary && !it.lock_mine && !it.lock_owner ? "🔓 Lock and open"
                                                               : "▶ Open", () => openIt(it)]);
    if (it.on_disk) {
      items.push(["🗂 Show in folder", () => api().reveal(it.path)]);
      items.push(["📋 Copy path", () => copyPaths([it.path])]);
      items.push(["🕘 History", () => openHistory(it.path)]);
    }
    if (it.lock_mine) {
      items.push(["", null]);
      items.push(["🔒 Release my lock", () => act("do_unlock", [[it.path]], "Releasing…")]);
    } else if (!it.lock_owner && it.on_disk && it.status !== "unversioned") {
      items.push(["", null]);
      items.push(["🔓 Lock", () => act("do_lock", [[it.path]], "Locking…")]);
    }
    if (srvOn()) items.push(["🌐 On the studio website", web]);
  }
  ctxMenu(ev.clientX, ev.clientY, items);
}

/* --- клавіатура: як у провіднику системи ---------------------------------- */
document.addEventListener("keydown", ev => {
  if (view !== "browse" || !$("modal").classList.contains("hidden")) return;
  const tag = (document.activeElement && document.activeElement.tagName) || "";
  if (tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT") return;
  if (ev.altKey && ev.key === "ArrowLeft") { ev.preventDefault(); return goBack(); }
  if (ev.altKey && ev.key === "ArrowRight") { ev.preventDefault(); return goFwd(); }
  if ((ev.altKey && ev.key === "ArrowUp") || ev.key === "Backspace") {
    ev.preventDefault();
    return goUp();
  }
  if (!brDir) return;
  const order = brDir.entries;
  if (ev.key === "ArrowDown" || ev.key === "ArrowUp") {
    ev.preventDefault();
    if (!order.length) return;
    let i = order.findIndex(x => x.path === brSel);
    i = i < 0 ? 0 : ev.key === "ArrowDown" ? Math.min(order.length - 1, i + 1)
                                           : Math.max(0, i - 1);
    const it = order[i];
    if (ev.shiftKey && brAnchor) {
      const a = order.findIndex(x => x.path === brAnchor);
      brPick.clear();
      for (let k = Math.min(a, i); k <= Math.max(a, i); k++) brPick.add(order[k].path);
    } else {
      brPick.clear(); brPick.add(it.path); brAnchor = it.path;
    }
    brSel = it.path;
    syncPick();
    showSelection();
    const node = [...$("br-list").children].find(n => n.dataset.k === "e:" + it.path);
    if (node) node.scrollIntoView({ block: "nearest" });
    return;
  }
  if (ev.key === "Enter") {
    const it = brSel && brEntry(brSel);
    if (!it) return;
    ev.preventDefault();
    if (it.kind === "dir") { if (!it.nested && !it.link) openDir(it.path); }
    else if (it.openable && it.on_disk) openIt(it);
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "c") {
    const paths = pickedOnDisk();
    if (paths.length) { ev.preventDefault(); copyPaths(paths); }
    return;
  }
  if ((ev.ctrlKey || ev.metaKey) && ev.key.toLowerCase() === "a") {
    ev.preventDefault();
    brPick.clear();
    order.forEach(x => brPick.add(x.path));
    syncPick();
    showSelection();
  }
});

/* Головна дія бінарника — «зайняти й відкрити». Порядок не косметичний:
   якщо відкрити спершу, а зайняти потім, людина попрацює в файлі, у який
   не має права писати, і зданий чужий день зникне при першому ж збереженні. */
async function openIt(it, after) {
  // Що оновити потім: у провіднику — поточну теку, у задачах — задачу.
  after = after || (() => openDir(brPath));
  const free = it.binary && !it.lock_mine && !it.lock_owner;
  if (free && pref("lock_open_silent")) {     // людина попросила не питати
    return act("open_file", [it.path, true], "Locking and opening…")
      .then(after);
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
        .then(after);
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

// Бічна панель для одного файлу. «Reading…» — лише коли вибрали ІНШИЙ файл:
// оновлення того самого (лок узяли) не має спершу стирати панель.
async function showSide(it) {
  brSel = it.path;
  brSelSig = JSON.stringify(it);
  if (it.kind === "dir") return renderFolderSide(it);
  const side = $("br-side");
  if (side.dataset.path !== it.path)
    side.innerHTML = "<div class='br-empty'>Reading…</div>";
  side.dataset.path = it.path;
  let d = null;
  if (it.on_disk) {
    try { d = await api().file_details(it.path); } catch (e) { d = null; }
  }
  if (brSel !== it.path || brPick.size > 1) return;   // людина вже вибрала інше
  renderSide(it, d);
}

function sideEmpty() {
  const side = $("br-side");
  side.dataset.path = "";
  side.innerHTML = "<div class='br-empty'>Pick a file to see it here</div>";
}

function dragHint() {
  return nativeDrag === true
    ? "Drag onto a folder to move it — or into Blender or Explorer to use a copy of it."
    : "Drag onto a folder to move it.";
}

function renderFolderSide(it) {
  const side = $("br-side");
  side.innerHTML = "";
  side.dataset.path = it.path;
  const plain = !it.nested && !it.link;
  const big = document.createElement("div");
  big.className = "br-bigico"; big.textContent = it.nested ? "📦" : it.link ? "🔗" : "📁";
  const nm = document.createElement("div");
  nm.className = "br-name"; nm.textContent = it.name;
  side.append(big, nm);
  const facts = [];
  if (it.nested) facts.push("a separate project inside this one");
  if (it.link) facts.push("a shortcut, not a real folder of the project");
  if (it.new_inside) facts.push("somebody submitted something in here");
  if (it.mine_inside) facts.push("you have unsubmitted work in here");
  if (it.status === "unversioned") facts.push("new — not in the project yet");
  if (it.moved_from) facts.push("moved here from " + (parentOf(it.moved_from) || "the project root"));
  for (const f of facts) side.append(dimLine(f));
  if (plain) side.append(mini("📂 Open", "", () => openDir(it.path)));
  side.append(mini("🗂 Show in folder", "", () => api().reveal(it.path)));
  side.append(mini("📋 Copy path", "", () => copyPaths([it.path])));
  if (plain) side.append(mini("🔓 Lock everything inside", "", () => folderLock(it)));
  if (srvOn() && plain)
    side.append(mini("🌐 On the studio website", "", () =>
      api().open_web("file", it.path).catch(e => fail(e))));
  if (plain) side.append(dimLine(dragHint()));
}

function renderMulti() {
  const side = $("br-side");
  side.innerHTML = "";
  side.dataset.path = "";
  brSelSig = null;
  const picked = ((brDir && brDir.entries) || []).filter(e => brPick.has(e.path));
  const nm = document.createElement("div");
  nm.className = "br-name";
  nm.textContent = picked.length + " items selected";
  side.append(nm);
  for (const e of picked.slice(0, 10)) {
    const r = document.createElement("div");
    r.className = "side-l mono-l";
    r.textContent = (e.kind === "dir" ? "📁 " : "") + e.name;
    side.append(r);
  }
  if (picked.length > 10) side.append(dimLine("…and " + (picked.length - 10) + " more"));
  const bytes = picked.reduce((a, e) => a + (e.size || 0), 0);
  if (bytes) side.append(dimLine(fmtSize(bytes) + " in files"));
  side.append(mini("📋 Copy " + picked.length + " paths", "",
                   () => copyPaths(pickedOnDisk())));
  side.append(dimLine(dragHint().replace("move it", "move them")
                                .replace("a copy of it", "copies of them")));
}

async function renderSide(it, d) {
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
    side.append(mini("📋 Copy path", "", () => copyPaths([it.path])));
    side.append(mini("🕘 History", "", () => openHistory(it.path)));
    side.append(dimLine(dragHint()));
  }
  if (!srvOn()) return;

  // --- те, що знає сервер студії ------------------------------------------
  // Картинка: для файлу, якого ще нема на диску, своєї немає — беремо ту,
  // що сервер уже витяг. Місце — те саме, згори панелі.
  if (!(d && d.preview) && PREVIEWABLE.test(it.name)) {
    const key = it.path + "@";
    const put = uri => {
      if (!uri || brSel !== it.path || side.querySelector(".br-thumb")) return;
      const img = document.createElement("img");
      img.className = "br-thumb"; img.src = uri; img.alt = "";
      img.title = "the picture from the server — the newest submitted version";
      side.prepend(img);
    };
    if (THUMBS.has(key)) put(THUMBS.get(key));
    else api().previews([{ path: it.path, rev: null }]).then(r => {
      THUMBS.set(key, r[key] || null); put(r[key]);
    }).catch(() => {});
  }

  const ts = tasksFor(it.path);
  if (ts.length) {
    const sec = sideSection(side, "Task");
    for (const t of ts.slice(0, 3)) sec.append(taskLine(t));
  }

  side.append(mini("🌐 On the studio website", "", () =>
    api().open_web("file", it.path).catch(e => fail(e))));

  if (it.kind === "file" && (/\.blend$/i.test(it.name) || USABLE.test(it.name))) {
    const wait = sideSection(side, "Links");
    wait.append(dimLine("asking the server…"));
    let l = null;
    try { l = await api().file_links(it.path); } catch (e) { l = null; }
    if (brSel !== it.path) return;
    wait.parentNode.remove();
    if (l && l.ok) renderLinks(side, l);
  }
}

/* --- що сцена тягне за собою і хто використовує файл -------------------- */
const LINK_WORD = {
  missing: ["missing", "the path points into the project, but there is no such file"],
  case: ["letter case", "works on Windows, breaks on the Linux render farm"],
  absolute: ["absolute path", "points into the project by a full path — works only on the author’s machine"],
  outside: ["outside the project", "a relative path that leads out of the project"],
};

function sideSection(side, title) {
  const wrap = document.createElement("div");
  wrap.className = "side-sec";
  const h = document.createElement("div");
  h.className = "side-h"; h.textContent = title;
  const body = document.createElement("div");
  body.className = "side-b";
  wrap.append(h, body);
  side.append(wrap);
  return body;
}

function dimLine(text, title) {
  const d = document.createElement("div");
  d.className = "side-l dim-l"; d.textContent = text;
  if (title) d.title = title;
  return d;
}

function renderLinks(side, l) {
  const dp = l.deps;
  if (dp) {
    const sec = sideSection(side, "Uses");
    if (dp.state === "pending") {
      sec.append(dimLine("the server has not read this scene yet — try again in a minute"));
    } else if (dp.state !== "ok") {
      sec.append(dimLine("could not read what it uses", dp.note || ""));
    } else {
      const c = dp.counts || {};
      const parts = [];
      if (dp.uses) parts.push(dp.uses + (dp.uses === 1 ? " file" : " files") + " of the project");
      if (c.external) parts.push(c.external + " from shared storage");
      if (c.packed) parts.push(c.packed + " packed inside");
      sec.append(dimLine(parts.length ? parts.join(" · ") : "nothing — the scene is self-contained",
        c.external ? "“from shared storage” — full paths outside SVN (X:\\…), read live " +
                     "from the NAS. That is how the studio does it, not a mistake." : ""));
      if (dp.newer_n) {
        const w = document.createElement("div");
        w.className = "side-l warn-l";
        w.textContent = (dp.newer_n === 1 ? "1 file it uses is" : dp.newer_n + " files it uses are") +
          " newer on the server — click “Get latest” before opening";
        w.title = dp.newer.join("\n");
        sec.append(w);
      }
      for (const p of dp.problems || []) {
        const [word, why] = LINK_WORD[p.state] || [p.state, ""];
        const r = document.createElement("div");
        r.className = "side-l bad-l";
        r.textContent = "⚠ " + p.name + " — " + word;
        r.title = why + "\n" + p.raw;
        sec.append(r);
      }
    }
  }
  const ub = l.used_by;
  if (ub && !ub.error) {
    const sec = sideSection(side, "Used by");
    if (!ub.n) {
      sec.append(dimLine(ub.complete ? "no scene uses this file"
        : "no scene so far — the server is still reading the project"));
    } else {
      for (const u of ub.users.slice(0, 8)) {
        const r = document.createElement("div");
        r.className = "side-l mono-l"; r.textContent = u; r.title = u;
        sec.append(r);
      }
      if (ub.n > 8) sec.append(dimLine("…and " + (ub.n - 8) + " more"));
      sec.append(dimLine("renaming or deleting this file breaks them"));
    }
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
  let failed = null;
  try {
    const r = await api()[method].apply(null, args || []);
    if (typeof r === "string") toast(r, 8000);
  } catch (e) {
    failed = e;
  }
  busy(false);
  if (failed) fail(failed);           // вікно відмови — вже без «Working…» під ним
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

  // Видалення текстури чи бібліотеки ламає сцени, що на неї посилаються, — і
  // ламає мовчки: колега відкриє сцену без неї аж завтра. Сервер знає, хто
  // що використовує, тож питаємо ДО здачі. Немає сервера — не питаємо.
  const byPath = new Map(((st && st.files) || []).map(f => [f.path, f]));
  const gone = [...selected].filter(p => {
    const f = byPath.get(p);
    return f && (f.status === "missing" || f.status === "deleted");
  });
  if (gone.length && srvOn()) {
    let ub = {};
    busy(true, "Checking what uses these files…");
    try { ub = await api().used_by_many(gone); } catch (e) { ub = {}; }
    busy(false);
    const hit = Object.keys(ub);
    if (hit.length) {
      const scenes = [...new Set(hit.flatMap(p => ub[p]))];
      const a = await ask({
        title: scenes.length === 1 ? "A scene still uses what you are deleting"
                                   : "Scenes still use what you are deleting",
        factsFirst: true,
        facts: hit.slice(0, 8).map(p => [p, ub[p].length === 1
          ? "used by 1 scene" : "used by " + ub[p].length + " scenes"]),
        lines: ["After this submit they will open without it:"]
          .concat(scenes.slice(0, 6).map(s => ({ text: s, mono: true })))
          .concat(scenes.length > 6 ? ["…and " + (scenes.length - 6) + " more"] : [])
          .concat(["If the file moved somewhere else, those scenes have to be " +
                   "pointed at the new place first."]),
        ok: "Delete anyway", danger: true,
      });
      if (!a.ok) return;
    }
  }

  const review = $("c-review").checked && !$("c-review-l").classList.contains("hidden")
    ? reviewTasks().map(t => t.id) : [];
  busy(true, "Submitting… big files can take a while");
  let failed = null;
  try {
    toast(await api().do_commit(Array.from(selected), msg,
                               $("c-keep").checked, review), 9000);
    selected.clear(); $("c-msg").value = ""; delete drafts[pid()];
    $("c-review").checked = false;
  } catch (e) { failed = e; }
  busy(false);
  if (failed) fail(failed);
  if (review.length) loadTasks(true);
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
    resetExplorer();
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
  if (t === "browse") { showView("browse"); return openDir(brPath, { history: true }); }
  if (t === "history") { showView("log"); return loadLog(); }
  if (t === "tasks") {
    showView("tasks"); renderTaskList();
    return loadTasks(true);           // вкладку відкрили — хочуть свіже
  }
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
  // Картинки змінених файлів — як у переглядачі на сайті. Місце під них є в
  // кожному рядку, щоб імена стояли рівно, а не стрибали там, де картинка
  // доїхала. Видалений файл показуємо таким, яким він був ДО коміту.
  const pics = srvOn();
  const want = [];
  for (const f of d.files) {
    const row = document.createElement("div");
    row.className = "ch-f";
    if (pics) {
      const th = document.createElement("span");
      th.className = "ch-thumb";
      row.append(th);
      if (f.kind !== "dir" && PREVIEWABLE.test(f.path) && want.length < 40) {
        const r = f.action === "D" ? Number(rev) - 1 : Number(rev);
        want.push({ path: f.path, rev: r, th: th });
      }
    }
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
  if (want.length) fillThumbs(want, () => logRev === rev);
}

/* Картинки з сервера в заготовлені місця. Уже бачене — з пам'яті одразу,
   решту — одним запитом (сервер качає їх паралельно). still() — чи людина
   досі дивиться туди ж: відповідь могла приїхати, коли вже обрано інше. */
const THUMBS = new Map();           // "шлях@ревізія" -> data:URI | null

async function fillThumbs(want, still) {
  const put = (w, uri) => {
    if (!uri) return;
    const im = document.createElement("img");
    im.src = uri; im.alt = "";
    w.th.replaceChildren(im);
  };
  const ask_ = [];
  for (const w of want) {
    const key = w.path + "@" + (w.rev == null ? "" : w.rev);
    if (THUMBS.has(key)) put(w, THUMBS.get(key));
    else ask_.push(w);
  }
  if (!ask_.length) return;
  let got = {};
  try {
    got = await api().previews(ask_.map(w => ({ path: w.path, rev: w.rev })));
  } catch (e) { return; }
  for (const w of ask_) {
    const key = w.path + "@" + (w.rev == null ? "" : w.rev);
    // «ще готується» не запам'ятовуємо: за хвилину картинка вже буде
    if (got[key]) THUMBS.set(key, got[key]);
    if (still()) put(w, got[key]);
  }
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

/* --- сервер студії: задачі ----------------------------------------------
   Усе нижче — доповнення. Немає сервера з API (інша програма, старий образ,
   офлайн) — вкладки задач немає, позначок немає, картинок немає, а решта
   APSVN працює так само. Жодна з цих функцій не має права зламати список
   змін чи здачу, тому кожна невдача тут тиха. */

// Що сервер уміє показати картинкою і що може бути залежністю .blend —
// ті самі списки, що в server_api.py (а там — як на сервері).
const PREVIEWABLE = /\.(blend|psd|psb|png|jpe?g|webp|gif|bmp|tga|tiff?)$/i;
const USABLE = /\.(blend|png|jpe?g|tga|tiff?|exr|hdr|bmp|webp|gif|psd|dds|jp2|cin|dpx|mp4|mov|avi|mkv|webm|mpe?g|ogv|wav|mp3|ogg|flac|aac|m4a|ttf|otf|woff2?|pfb|abc|usd[acz]?|vdb)$/i;
const STATUS_NAME = { todo: "To do", wip: "In progress", wfa: "Review",
                      retake: "Retake", done: "Done" };

let srvInfo = null;               // server_status()
let tasksData = null;             // tasks_overview()
let tasksSigLast = null;          // щоб не перемальовувати без змін
let taskSel = null;               // відкрита праворуч задача
let taskDone = null;              // мої завершені — лише на вимогу
let srvPid = null;                // для якого проєкту все це

const srvOn = () => !!(srvInfo && srvInfo.ok);
const tasksOn = () => !!(srvInfo && srvInfo.ok && srvInfo.tasks);
const myTasks = () => ((tasksData && tasksData.tasks) || []).filter(t => t.mine);

async function initServer() {
  const mine = gen;
  let s = null;
  try { s = await api().server_status(false); } catch (e) { s = null; }
  if (mine !== gen) return;
  srvInfo = s;
  // «ще невідомо» — копію ще не читали (іде передача). Спитаємо трохи згодом.
  // Сервер не відповів — теж спитаємо ще, коли мине його пам'ять про невдачу
  // (хвилина; для відмови в паролі — п'ять). Інакше після ранку без мережі
  // задачі не з'явилися б до перезапуску програми.
  const again = !s ? 65000 : s.why === "later" ? 4000
    : s.why === "error" ? ((s.code === 401 || s.code === 429) ? 310000 : 65000)
    : 0;
  if (again) setTimeout(() => { if (mine === gen) initServer(); }, again);
  renderTaskBadge();
  if (tasksOn()) loadTasks(false);
  else if (view === "tasks") { showView("files"); renderFiles(); }
}

async function loadTasks(force) {
  if (!tasksOn()) return;
  const mine = gen;
  let o = null;
  try { o = await api().tasks_overview(!!force); } catch (e) { o = null; }
  if (mine !== gen || !o) return;
  tasksData = o;
  const sig = JSON.stringify([o.error || "", (o.tasks || []).map(
    t => [t.id, t.status, t.assignees, t.local, t.due, t.overdue])]);
  const changed = sig !== tasksSigLast;
  tasksSigLast = sig;
  renderTaskBadge();
  // Як і список змін: без змін — не перемальовуємо, інакше щопівхвилини
  // картка під курсором втрачала б підсвітку, а прокрутка — місце.
  if (changed && view === "tasks") renderTaskList();
  if (changed && view === "files") renderFiles();   // позначки в рядках
  else syncBar();
}

// Задачі, що накривають файл: на ньому самому або на теці над ним (так само
// рахує й сервер, зокрема для м'якого локу). Найближча — першою.
function tasksFor(path) {
  const p = String(path || "").replace(/^\/+|\/+$/g, "");
  return ((tasksData && tasksData.tasks) || [])
    .filter(t => t.local != null &&
            (t.local === p || t.local === "" || p.startsWith(t.local + "/")))
    .sort((a, b) => b.local.length - a.local.length);
}

function taskSig(path) {
  return tasksFor(path).map(t => t.id + t.status + t.assignees.join()).join("|");
}

/* Позначка задачі в рядку. Своя — статусом і кольором; чужа — ІМЕНЕМ: саме
   це людина має знати ще до того, як спробує зайняти файл. Якщо в проєкті
   ввімкнено м'який лок, сервер однаково не дасть — але краще знати наперед,
   ніж дізнатися з відмови. */
function taskChip(path) {
  const ts = tasksFor(path);
  if (!ts.length) return null;
  return chipOfTask(ts.find(x => x.mine) || ts[0]);
}

function chipOfTask(t) {
  const c = document.createElement("button");
  if (t.mine) {
    // Коротко: у рядку поруч ще статус файлу, кнопки й лок, а ім'я файлу
    // важливіше за все це. Тип і термін — у підказці та на вкладці задач.
    c.className = "chip task st-" + t.status;
    c.textContent = "📋 " + t.status_name;
    c.title = "your task: " + (t.type || "task") + " · " + t.status_name +
      (t.due ? " — due " + t.due : "") + ". Click to open it.";
  } else {
    const who = t.assignees.join(", ") || "nobody yet";
    c.className = "chip task other";
    c.textContent = "📋 " + who;
    c.title = (t.type || "task") + " · " + t.status_name + " — assigned to " + who +
      ". If the project uses soft locks, only they or a supervisor can lock and submit it.";
  }
  c.onclick = ev => { ev.stopPropagation(); openTask(t.id); };
  return c;
}

function taskLine(t) {
  const r = document.createElement("div");
  r.className = "side-l";
  r.append(chipOfTask(t));
  if (t.is_dir) {                   // задача на теці накриває і цей файл
    const w = document.createElement("span");
    w.className = "dim-l"; w.textContent = " — on the folder " + (t.local || "(project)");
    r.append(w);
  }
  return r;
}

// Мої задачі, які ця здача може відправити на перевірку: вибрано сам файл
// задачі, щось усередині теки задачі або теку, всередині якої вона лежить.
function reviewTasks() {
  if (!tasksData || !selected.size) return [];
  const out = new Map();
  for (const p of selected) {
    for (const t of tasksData.tasks || []) {
      if (!t.mine || t.local == null ||
          !["todo", "wip", "retake"].includes(t.status)) continue;
      if (t.local === p || t.local === "" || p.startsWith(t.local + "/") ||
          t.local.startsWith(p + "/"))
        out.set(t.id, t);
    }
  }
  return [...out.values()];
}

function renderTaskBadge() {
  $("tab-tasks-btn").classList.toggle("hidden", !tasksOn());
  const mine = myTasks();
  // рахуємо те, що чекає ДІЇ від людини; «на перевірці» чекає керівника
  const todo = mine.filter(t => t.status !== "wfa").length;
  const hot = mine.some(t => t.status === "retake" || t.overdue);
  const b = $("tasks-n");
  b.textContent = todo ? String(todo) : "";
  b.classList.toggle("hidden", !todo);
  b.classList.toggle("hot", hot);
  $("tab-tasks-btn").title = hot ? "some of your tasks were sent back, or are overdue" : "";
}

const TASK_GROUPS = [
  ["retake", "Sent back", "your supervisor asked for changes"],
  ["wip", "In progress", "what you are working on"],
  ["todo", "To do", "not started yet"],
  ["wfa", "Waiting for review", "your supervisor will look at these"],
];

function taskOrder(a, b) {
  if (a.overdue !== b.overdue) return a.overdue ? -1 : 1;
  if ((a.due || "9") !== (b.due || "9")) return (a.due || "9") < (b.due || "9") ? -1 : 1;
  return a.name.localeCompare(b.name);
}

function renderTaskList() {
  const box = $("tasks-list");
  $("tasks-title").textContent = "My tasks in “" + ((st && st.name) || "") + "”";
  const err = tasksData && !tasksData.ok && tasksData.error;
  $("tasks-warn").textContent = err ? "Could not refresh the tasks: " + err : "";
  $("tasks-warn").classList.toggle("hidden", !err);
  if (!tasksData) {
    box.innerHTML = "<div class='empty'>Reading your tasks…</div>";
    return;
  }
  const out = [], want = [];
  const card = t => {
    const c = document.createElement("div");
    c.className = "tk" + (t.id === taskSel ? " on" : "") + (t.gone ? " gone" : "");
    const th = document.createElement("div");
    th.className = "tk-thumb";
    th.textContent = t.is_dir ? "📁" : "📋";
    if (!t.is_dir && t.local != null && PREVIEWABLE.test(t.local))
      want.push({ path: t.local, rev: null, th: th });
    const body = document.createElement("div");
    body.className = "tk-body";
    const nm = document.createElement("div");
    nm.className = "tk-name"; nm.textContent = t.name;
    const sub = document.createElement("div");
    sub.className = "tk-sub";
    const bits = [];
    if (t.type) bits.push(t.type);
    if (t.local == null) bits.push("not in your copy of the project");
    else if (t.local.includes("/")) bits.push(t.local.slice(0, t.local.lastIndexOf("/") + 1));
    sub.textContent = bits.join(" · ");
    body.append(nm, sub);
    if (t.due) {
      const due = document.createElement("div");
      due.className = "tk-due" + (t.overdue ? " late" : "");
      due.textContent = (t.overdue ? "overdue — was due " : "due ") + t.due;
      body.append(due);
    }
    c.append(th, body, chip(t.status_name, "st st-" + t.status));
    c.onclick = () => openTask(t.id);
    return c;
  };
  const head = (title, n, hint) => {
    const h = document.createElement("div");
    h.className = "grp";
    h.innerHTML = "<span class='gt'></span><span class='gn'></span><span class='gh'></span>";
    h.children[0].textContent = title;
    h.children[1].textContent = n;
    h.children[2].textContent = hint;
    return h;
  };

  const mine = myTasks();
  for (const [status, title, hint] of TASK_GROUPS) {
    const rows = mine.filter(t => t.status === status).sort(taskOrder);
    if (!rows.length) continue;
    out.push(head(title, rows.length, hint));
    for (const t of rows) out.push(card(t));
  }
  if (!mine.length) {
    const e = document.createElement("div");
    e.className = "empty tasks-empty";
    e.textContent = "Nothing assigned to you in this project right now 🎉";
    out.push(e);
  }
  if (taskDone === null) {
    const b = mini("Show my finished tasks", "", async () => {
      try { taskDone = await api().tasks_done(); } catch (e) { return fail(e); }
      renderTaskList();
    });
    b.classList.add("tk-more");
    out.push(b);
  } else if (taskDone.length) {
    out.push(head("Done", taskDone.length, "accepted by your supervisor"));
    for (const t of taskDone) out.push(card(t));
  } else {
    const e = document.createElement("div");
    e.className = "tk-none"; e.textContent = "No finished tasks yet.";
    out.push(e);
  }
  const top = box.scrollTop;
  box.replaceChildren(...out);
  box.scrollTop = top;
  if (want.length) fillThumbs(want, () => view === "tasks");
}

async function openTask(id) {
  taskSel = id;
  if (view !== "tasks") showView("tasks");
  renderTaskList();
  const side = $("task-side");
  side.innerHTML = "<div class='br-empty'>Reading the task…</div>";
  let d = null;
  try { d = await api().task_detail(id); }
  catch (e) {
    if (taskSel === id) side.innerHTML = "<div class='br-empty'>Could not read this task</div>";
    return fail(e);
  }
  if (taskSel !== id) return;
  renderTaskSide(d);
}

function agoEpoch(sec) {
  if (!sec) return "";
  const d = new Date(sec * 1000);
  const pad = n => String(n).padStart(2, "0");
  return ago(d.getFullYear() + "-" + pad(d.getMonth() + 1) + "-" + pad(d.getDate()) +
             " " + pad(d.getHours()) + ":" + pad(d.getMinutes()));
}

// Що сталося — людськими словами. Коментар до зміни статусу («руки
// переробити») показується окремою бульбашкою: це найважливіше в стрічці.
const EVENT_TEXT = {
  created: e => "created the task" + (e.new ? " for " + e.new : ""),
  status: e => (e.old ? (STATUS_NAME[e.old] || e.old) + " → " : "") +
               (STATUS_NAME[e.new] || e.new),
  auto: e => (STATUS_NAME[e.old] || e.old) + " → " + (STATUS_NAME[e.new] || e.new) +
             " — on the first commit" + (e.rev ? " (commit " + e.rev + ")" : ""),
  comment: () => "commented",
  assign: e => "assigned it to " + (e.new || "nobody"),
  edit: e => "changed the " + (e.comment || "task") + ": " + (e.old || "—") +
             " → " + (e.new || "—"),
  moved: e => "the file moved: " + e.old + " → " + e.new,
  gone: () => "the file was removed from the project",
  back: () => "the file is back in the project",
};

// Незданого рецензент не побачить. Вміст теки задачі теж рахується.
function unsubmittedUnder(local) {
  if (local == null) return [];
  return ((st && st.files) || []).filter(f => isMine(f) &&
    (local === "" || f.path === local || f.path.startsWith(local + "/")));
}

function renderTaskSide(d) {
  const side = $("task-side");
  side.innerHTML = "";
  if (d.preview) {
    const img = document.createElement("img");
    img.className = "br-thumb"; img.src = d.preview; img.alt = "";
    side.append(img);
  }
  const nm = document.createElement("div");
  nm.className = "br-name"; nm.textContent = d.name;
  side.append(nm);
  const where = document.createElement("div");
  where.className = "tk-path";
  where.textContent = d.local != null ? (d.local || "(the whole project)")
                                      : d.path + " — not in your copy";
  side.append(where);

  const fact = (k, v, cls) => {
    if (v == null || v === "") return;
    const r = document.createElement("div");
    r.className = "br-fact";
    const a = document.createElement("span"); a.textContent = k;
    const b = document.createElement("b"); b.textContent = v;
    if (cls) b.className = cls;
    r.append(a, b); side.append(r);
  };
  const stRow = document.createElement("div");
  stRow.className = "br-fact";
  const stK = document.createElement("span"); stK.textContent = "status";
  stRow.append(stK, chip(d.status_name, "st st-" + d.status));
  side.append(stRow);
  fact("type", d.type);
  fact("assigned to", d.assignees.join(", ") || "nobody yet");
  if (d.due) fact("due", d.due + (d.overdue ? " — overdue" : ""), d.overdue ? "late" : "");
  fact("set by", d.created_by);
  if (d.gone) fact("file", "no longer in the project", "late");

  // Кроки — лише дозволені виконавцю; «прийняти» й «повернути» —
  // справа керівника, і кнопок, які завжди відмовлять, тут немає.
  const acts = document.createElement("div");
  acts.className = "tk-acts";
  for (const to of d.moves || []) {
    if (to === "wfa") {
      const b = mini("✔ Send to review", "go", () => sendToReview(d));
      acts.append(b);
    } else if (to === "wip") {
      acts.append(mini(d.status === "todo" ? "▶ Start working" : "↩ Back to work",
                       "", () => moveTask(d, "wip")));
    }
  }
  if (acts.children.length) side.append(acts);
  if (!d.mine)
    side.append(dimLine("Assigned to " + (d.assignees.join(", ") || "nobody") +
                        " — only they or a supervisor move it."));
  else if (d.status === "wfa")
    side.append(dimLine("Waiting for your supervisor — they accept it or send it back."));
  else if (d.status === "done")
    side.append(dimLine("Accepted — nothing left to do here."));

  // Файл задачі — ті самі дії, що в провіднику, і з тим самим «зайняти
  // перед відкриттям».
  if (d.local != null) {
    const f = ((st && st.files) || []).find(x => x.path === d.local) || {};
    if (d.on_disk && d.openable) {
      const it = { path: d.local, name: d.name, binary: d.binary,
                   lock_mine: f.lock_mine, lock_owner: f.lock_owner };
      side.append(mini(d.binary && !f.lock_mine ? "🔓 Lock and open" : "▶ Open", "",
                       () => openIt(it, () => loadTasks(true))));
    }
    if (d.on_disk || d.is_dir)
      side.append(mini("📂 Show in folder", "", () => api().reveal(d.local)));
    if (d.on_disk)
      side.append(mini("🕘 History", "", () => openHistory(d.local)));
  }
  side.append(mini("🌐 On the studio website", "", () =>
    (d.local != null ? api().open_web("file", d.local)
                     : api().open_web("repo", d.path)).catch(e => fail(e))));

  // Коментар — без зміни статусу: питання керівнику, «так і задумано» тощо.
  const sec = sideSection(side, "Comments and history");
  const ta = document.createElement("textarea");
  ta.className = "tk-comment"; ta.rows = 2;
  ta.placeholder = "Write a comment…";
  const send = mini("Send", "", async () => {
    const text = ta.value.trim();
    if (!text) return;
    send.disabled = true;
    try { await api().task_comment(d.id, text); }
    catch (e) { send.disabled = false; return fail(e); }
    openTask(d.id);
  });
  ta.onkeydown = e => { if (e.key === "Enter" && e.ctrlKey) send.click(); };
  const row = document.createElement("div");
  row.className = "tk-comment-row";
  row.append(ta, send);
  sec.append(row);

  for (const e of d.events || []) {
    const ev = document.createElement("div");
    ev.className = "tk-ev";
    const h = document.createElement("div");
    h.className = "tk-ev-h";
    const who = document.createElement("b"); who.textContent = e.user || "server";
    const what = (EVENT_TEXT[e.kind] || (() => e.kind))(e);
    h.append(who, " " + what);
    const t = document.createElement("span");
    t.className = "tk-ev-t"; t.textContent = agoEpoch(e.at);
    h.append(t);
    ev.append(h);
    if (e.comment && e.kind !== "edit") {
      const c = document.createElement("div");
      c.className = "tk-ev-c"; c.textContent = e.comment;
      ev.append(c);
    }
    sec.append(ev);
  }
}

async function moveTask(d, to, comment) {
  busy(true, "Updating the task…");
  let r = null, failed = null;
  try { r = await api().task_move(d.id, to, comment || ""); }
  catch (e) { failed = e; }
  busy(false);
  if (failed) return fail(failed);
  toast(r, 6000);
  await loadTasks(true);
  openTask(d.id);
}

async function sendToReview(d) {
  const lines = ["Your supervisor will look at it and either accept it or send " +
                 "it back with notes."];
  // Рецензент дивиться те, що на сервері. Нездане він не побачить — і
  // поверне задачу за роботу, яку людина насправді зробила.
  const dirty = unsubmittedUnder(d.local);
  if (dirty.length)
    lines.push({ text: (dirty.length === 1 ? "You have an unsubmitted change here"
                        : "You have " + dirty.length + " unsubmitted changes here") +
                       " — your supervisor will not see it. Submit first.", warn: true });
  const a = await ask({
    title: "Send “" + d.name + "” to review?",
    lines: lines,
    input: { placeholder: "A note for your supervisor (optional)" },
    ok: "Send to review",
  });
  if (a.ok) moveTask(d, "wfa", a.text);
}

// Обидві сторони конфлікту картинками — з диска (svn лишає поруч копію того,
// що приїхало від колеги), а сервер — лише якщо копії нема. Без картинок
// діалог той самий, що й був.
async function conflictPics(f, k) {
  if (k === "prop" || k === "moved") return null;
  let pv = null;
  try { pv = await api().conflict_previews(f.path); } catch (e) { pv = null; }
  if (!pv || (!pv.mine && !pv.theirs)) return null;
  const theirs = k === "tree" ? "The team’s — moved or deleted"
    : k === "obstructed" ? "The team’s file"
    : "Your colleague’s" + (pv.theirs_rev ? " — commit " + pv.theirs_rev : "");
  return [["Yours — on your disk now", pv.mine], [theirs, pv.theirs]];
}

$("tasks-web").onclick = () => api().open_web("mine").catch(e => fail(e));
$("tasks-board").onclick = () => api().open_web("board").catch(e => fail(e));

/* --- опитування: наступне лише після завершення попереднього ----------- */

function loop() {
  clearTimeout(timer);
  timer = setTimeout(async () => {
    if ($("busy").classList.contains("hidden") &&
        $("setup").classList.contains("hidden") && view !== "file") {
      try { await refresh(); } catch (e) { /* наступний оберт спробує ще */ }
    }
    loop();
  }, 10000);                          // локи чужих людей мають з’являтись швидко
}

window.addEventListener("pywebviewready", () => {
  refresh();
  loop();
  api().drag_supported().then(v => {
    nativeDrag = !!v;
    if (brDir) renderDir(brDir);          // рядки перебудуються під свій жест
  }).catch(() => { nativeDrag = false; });
  // Задачі — власним, повільнішим кроком: вони змінюються рідко, а сервер
  // однаково пам'ятає список 40 с. Поки йде передача — не смикаємо.
  setInterval(() => {
    if (tasksOn() && $("busy").classList.contains("hidden")) loadTasks(false);
  }, 30000);
  // тихо, один раз: якщо нового немає — художник про це навіть не дізнається
  setTimeout(() => checkUpdate(true), 3000);
});
