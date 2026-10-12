# macOS: що змінилося з останньої перевірки на Mac

Передача для сесії на Mac (жовтень 2026). Після портування цей файл можна
прибрати.

**Точка відліку.** Останній коміт, зроблений і перевірений на Mac, —
`071fa7c` (2026-09-01). Усе після нього — `eb2b98d`…`cdc2702`, близько 30
комітів — писалося й перевірялося **лише на Windows**. На Windows зелене:
972 перевірки без сервера й 17 живих (лише читання) на `cdc2702`.

**Завдання.** Довести все це до ладу на macOS. Зібрати `.app`, прогнати всі
`tests/test_*.py`, закрити дірки нижче. Поведінку на Windows не міняти.

Повний перелік змін:

```bash
git log --oneline 071fa7c..HEAD
git diff --stat 071fa7c..HEAD
```

Пояснення до кожного рішення — у `docs/README.md` («Decisions that should not
be “simplified”»).

---

## 1. Відомі вади на Mac — виправити

### 1.1 Потік замірів падає одразу — смуга здачі стоїть

`app/svn_client.py`, `_stream_lines()`. Потік `sample()` кличе
`_io_counts(p._handle)` поза `try`. На POSIX у `Popen` немає `_handle`, тож
перший же замір дає `AttributeError`, і потік помирає.

Вада стара (`_io_read(p._handle)` стоїть так із першого коміту `cd4840b`).
Раніше через неї на Mac лише не було швидкості. Тепер `on_io` — це те, що
рухає смугу здачі між рядками svn, тож на Mac вона стоятиме на 0% до самого
«Committing transaction».

Ліки: передавати `_io_counts` сам `p` (або pid), а не `p._handle`.

### 1.2 Смуга здачі на Mac усе ще рахує мережу, а не файли

`39cd818`: смуга стоїть на тому, скільки svn.exe **записав** — нову копію
файлу в `.svn`, рівно 1.00× розміру. Мережею ж змінений файл їде лише
різницею. На Windows це `GetProcessIoCounters → WriteTransferCount`
(`_io_counts`), і вісім справжніх здач по https дали 1.00x. Дослід:

| здача                      | прочитано | записано | мережею |
|----------------------------|-----------|----------|---------|
| новий 400 МБ               | 1.00×     | 1.00×    | 1.00×   |
| змінено чверть, розкидано  | 2.00×     | 1.00×    | 0.25×   |
| змінено все                | 2.00×     | 1.00×    | 1.00×   |
| той самий розмір, 1 МБ     | 4.00×     | 1.00×    | 0.00×   |

На Mac `_io_counts` повертає `None`, а `_Notifier` вмикає `track` лише при
`desktop.WINDOWS`. Тому там `basis == "network"` — та сама оманлива смуга,
яку цей коміт лікував: «0% · 60 хв» на зміненому `.blend`.

Що зробити:
* `proc_pid_rusage(pid, RUSAGE_INFO_V2)` з libproc через ctypes, поле
  `ri_diskio_byteswritten`. Перевірити, що це логічні байти, а не фізичні
  записи з запізненням кешу.
* Якщо лагає — стежити, як росте тимчасова копія в `.svn/tmp`: svn пише її,
  поки шле файл.
* Потім увімкнути `track` на Mac і зняти відповідні умови в `tests/test_meter.py`
  (розділ 4 чекає `basis == "files"`; розділ 7 стоїть за `WINDOWS`).

Як міряв я (скрипти були тимчасові, у репо їх немає):
1. Локальний `svnserve`; у Homebrew він іде разом із `subversion`.
2. Перед ним TCP-труба з лічильником і обмеженням 30 МБ/с.
3. Файл 1 ГБ: дві третини з дрібними правками, третина нова.
4. Справжній `sc.commit(..., track_writes=True)`, події кожні 0.4 с.
5. Порівняв, що показала б смуга, з реальною тривалістю.

### 1.3 Кошик на Mac — не перевірено, і питатиме дозволу

`app/desktop.py`, `to_recycle_bin()`. На Mac там
`osascript 'tell application "Finder" to delete …'`. Це писалося наосліп, а
на першому виклику macOS спитає дозволу керувати Finder (Automation).
Краще `NSFileManager.defaultManager().trashItemAtURL_resultingItemURL_error_()`
через PyObjC: бекенд pywebview на Cocoa його вже тягне — перевірити, чи є
він у `vendor` збірки. Повертати шляхи, що лишились на місці. Перевірити
вручну на одному тестовому файлі (я так перевірив Windows).

### 1.4 Слова «Recycle Bin», «Explorer», «Windows» в інтерфейсі

`cdc2702`, 🗂 Files not on the server:
* `ui/app.js`: `renderLocalOnly` (кнопка «Move to Recycle Bin…»),
  `recycleJunk` (текст вікна згоди, зокрема «If a drive has no Recycle Bin,
  Windows asks first»);
* `app/app.py`: `recycle_junk` (повідомлення «Moved … to the Recycle Bin»,
  «the Recycle Bin was not available»).

На Mac має бути «Trash». Наприклад, одна назва з `desktop` у стан для
інтерфейсу. Тести в `tests/test_local_only.py` порівнюють ці рядки — оновити
їх разом із текстом. Підказка 📂 уже бере Finder/Explorer з `navigator.platform`.

---

## 2. Написано під Mac наосліп — перевірити наживо

* **Збірка.**
  * `eb2b98d` переніс код у `app/`, а збиральні скрипти — у `build/`.
  * `build/package_mac.sh` правився під нову розкладку, але на Mac не
    запускався.
  * README (розділ macOS) досі велить `./make_runtime_mac.sh` з кореня.

  Зібрати `.app`, запустити, перевірити, що вікно встає.
* **Лічильник на трубі** (`0a8e66b`, `c40e93f`, `app/meter.py`).
  * Як він працює: окремий процес `python -u app/meter.py --serve` через
    `sys.executable` — CONNECT-тунель на 127.0.0.1; svn іде через нього
    ключем `--config-option servers:global:http-proxy-*`, лише на одну
    команду.
  * Брандмауер macOS може спитати дозволу на сокет. Якщо тунель не
    дійшов до сервера, здача сама повторюється напряму, і в
    `~/Library/Application Support/APSVN/apsvn.log` з'являється рядок про
    це.
  * У `tests/test_live.py` є перевірка `svn log` через лічильник, лише
    читання.
* **Blender студії й проєкту** (`b76415c`, `8765624`, `app/blender.py`).
  * Пошук: `_mac_installed()` — `/Applications`, `~/Applications`,
    `Blender*.app`, версія з `Info.plist`.
  * Запуск: `launch()` через `open -a`.
  * Перевірити з двома Blender: `Blender.app` і, скажімо,
    `Blender 5.2.app`.
* **Лікування після відкоту сервера** (`ecc51dd`, `svn_client.repair_rollback`).
  * Жорсткі посилання (`os.link`): на APFS ок; на SMB/NAS — запасна копія,
    повільно для великих `.blend`.
  * На Mac argv у UTF-8, тож 8.3-псевдоніми й заглушки не потрібні
    (`_argv_rel` пропускає шлях як є).
  * Перевірити NFD/NFC: кирилиця з «й/ї» в іменах (APFS нечутлива до
    нормалізації, а порівняння рядків у плані й `_put_back` — чутливі).
    `tests/test_rollback.py` має «Сцена.blend» — додати ім'я з «й».
* **Тема студії** (`23bd585`). `desktop.caption_colors` — лише Windows
  (кольори заголовка DWM). На Mac — нічого. За бажання можна задати
  `NSWindow` темний вигляд, коли тло студії темне.
* **Перетягування файлів у Blender** (`34b57d8`) — лише Windows (WinForms
  `DoDragDrop`). На Mac `drag_supported` дає `False`. Відома дірка,
  необов'язково.
* **svn.** SlikSvn 1.14.5 (`d0adf3a`) — лише Windows. На Mac svn з Homebrew
  (`build/make_svn_mac.sh`). `tests/test_apsvn.py` вимагає svn ≥ 1.14.4.

---

## 3. Варто обговорити з користувачем (міняє і Windows)

**Вирішено 2026-10-12 — «ховати й давати прибрати».** `JUNK_RE` і
`global-ignores` (крім `Icon`: CR у конфіг не запишеш, його ховає
`JUNK_RE`), плюс `__MACOSX`; службові теки в 🗂 — одним рядком серед
тимчасового, у Кошик цілком. Тести — `test_local_only.py`, розділ 3
(`Icon` — лише на Mac: Windows такого імені не створює).

**Мотлох з Mac** у 🗂 Files not on the server і в Changes:
* `._*` — AppleDouble на SMB і exFAT, Mac плодить їх і на спільних шарах;
* `Icon\r`, `.Spotlight-V100`, `.Trashes`, `.fseventsd`.

`.DS_Store` уже в `JUNK_RE` і в `global-ignores`. Додати решту — це зміна і
для Windows: таке лежить і на спільних шарах. Спитати перед тим.

---

## 4. Тести

Нові або сильно змінені після `071fa7c`:
* `test_meter.py` — лічильник, поступ, підсумок здачі;
* `test_rollback.py` — відкіт сервера;
* `test_local_only.py` — 🗂 і Кошик (Кошик у тесті підмінено);
* `test_tidy.py` — прибирання `.svn/pristine`;
* `test_server.py` — сервер студії, хуки: `.bat` на Windows, `sh` деінде —
  уже розведено;
* `test_progress.py`, `test_blender.py`, `test_projects.py`,
  `test_refresh.py`, `test_history.py`.

Віндове вже стоїть за `desktop.WINDOWS`: `test_meter` розділ 7, `test_server`,
`test_blender`, `test_explorer`. Живі перевірки (`test_live.py`) — лише
читання; писати на сервер — тільки з явного дозволу користувача на кожну дію.

## 5. Правила проєкту (коротко)

* Нічого не ламати на Windows. Після змін на Mac Windows має лишатися
  зеленою — скажіть користувачу, що там треба прогнати тести ще раз.
* Робота художника понад усе: ані автоматика, ані лікування ніколи не
  видаляють і не перезаписують його файлів.
* Код сервера (`SVN-Admin`) не правити. Чого бракує — прохання через
  користувача.
* README — англійською; коментарі в коді — українською, як довкола.
  Коміти — дрібні, з поясненням «чому».
