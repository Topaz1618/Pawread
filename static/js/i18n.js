/* Pawread 国际化
 *
 * 语言选择存在 localStorage，全站共用。
 * 文案表放在这里，前端按 `data-i18n` 属性替换文本节点。
 *
 * **书名译名**由后端处理 —— `data/booklists/*.json` 里每本书有
 * `translations` 字典，前端按当前语言查表，查不到退回原名。
 * 这一层不用翻译表，它查的是书的数据。
 */

(function () {
  'use strict';

  /** 文案表。 */
  const I18N = {
    cn: {
      'nav.ingest': '操作',
      'nav.library': '书单',
      'nav.reader': '阅读',
      'ingest.title': '读书作业',
      'ingest.desc': '粘贴书名，每行一个，一次最多 100 本。中英文西德文都可以 —— 中文书名会自动译成英文原标题再检索。',
      'ingest.label': '书名清单',
      'ingest.lang': '语言',
      'ingest.submit': '开始处理',
      'ingest.queue': '处理队列',
      'ingest.empty': '还没有任务',
      'ingest.emptyHint': '在上面粘贴书名开始',
      'ingest.count': '{n} 本',
      'ingest.submitted': '已提交 {n} 本',
      'ingest.maxBooks': '一次最多 100 本',
      'ingest.read': '阅读',
      'ingest.source': '来源',
      'lib.badge': '我的收藏书架',
      'lib.title': '我的书单',
      'lib.desc': '按优先级筛选，点击任意一本进入阅读模式。',
      'lib.all': '全部书籍',
      'lib.priority': '优先级',
      'lib.status': '状态',
      'lib.search': '搜索书名或译名…',
      'lib.colTitle': '书名',
      'lib.colZh': '中文译名',
      'lib.colPrio': '优先级',
      'lib.colState': '状态',
      'lib.empty': '没有符合条件的书',
      'lib.summary': '显示 {shown} / {total}　有笔记 {noted}',
      'lib.unranked': '未分级',
      'lib.hasNote': '有笔记',
      'reader.shelf': '书单',
      'reader.allBooks': '全部书籍',
      'reader.noNote': '还没有笔记',
      'reader.loading': '载入中…',
      'reader.back': '书单',
      'state.pending': '排队中',
      'state.searching': '检索资源',
      'state.downloading': '下载中',
      'state.verifying': '校验内容',
      'state.noting': '生成笔记',
      'state.available': '资源就位',
      'state.noted': '已完成',
      'state.unavailable': '未找到',
      'state.failed': '失败',
      'group.noted': '有笔记',
      'group.active': '处理中',
      'group.unavailable': '未找到',
      'group.failed': '失败',
      'group.pending': '未处理',
      'prio.0': 'P0 最高',
      'prio.1': 'P1 第二',
      'prio.2': 'P2 第三',
      'prio.3': 'P3 第四',
      'ingest.badge': 'Pawread 读书台',
      'ingest.ph': '粘贴书名，每行一个…\nThinking in Systems\n穷查理宝典\nEl principito',
      'ingest.f1t': '多语言检索',
      'ingest.f1d': '中文、西班牙语、德语书名都会先归一到英文原标题再检索。',
      'ingest.f2t': '完整笔记',
      'ingest.f2d': '不压缩、不改原意，原文引用逐句保留。',
      'ingest.f3t': '分层阅读',
      'ingest.f3d': '每份笔记带目录与要点预览，随时跳读。',
      'lib.read': '阅读',
      'reader.progress': '阅读进度',
      'reader.reading': '阅读中',
      'ingest.hint': '每行一个书名，一次最多 100 本',
      'ingest.privacy': '中文、西语、德语书名会自动归一到英文原标题再检索',
      'ingest.search': '搜索书名或编号…',
      'ingest.guarantee': '阅读保障与协助',
      'ingest.noFile': '尚无文件',
      'ingest.detail': '查看详情',
      'ingest.readNote': '阅读笔记',
      'ingest.downloadNote': '下载笔记',
      'ingest.guaranteeDesc': '免费合规资源的检索与下载会全程留痕。找不到的书会在队列里标明原因，你也可以在书单页查看全部未完成的任务。',
      'group.all': '全部',
    },
    en: {
      'nav.ingest': 'Ingest',
      'nav.library': 'Library',
      'nav.reader': 'Read',
      'ingest.title': 'Reading Queue',
      'ingest.desc': 'Paste book titles, one per line, up to 100 at a time. Chinese, English, Spanish and German titles are all accepted — Chinese ones are translated to their original English titles before searching.',
      'ingest.label': 'Book titles',
      'ingest.lang': 'Language',
      'ingest.submit': 'Start',
      'ingest.queue': 'Processing queue',
      'ingest.empty': 'No tasks yet',
      'ingest.emptyHint': 'Paste titles above to begin',
      'ingest.count': '{n} books',
      'ingest.submitted': 'Submitted {n} books',
      'ingest.maxBooks': 'Up to 100 books at a time',
      'ingest.read': 'Read',
      'ingest.source': 'Source',
      'lib.badge': 'My Reading Shelf',
      'lib.title': 'My Library',
      'lib.desc': 'Filter by priority, click any book to start reading.',
      'lib.all': 'All books',
      'lib.priority': 'Priority',
      'lib.status': 'Status',
      'lib.search': 'Search title or translation…',
      'lib.colTitle': 'Title',
      'lib.colZh': 'Translation',
      'lib.colPrio': 'Priority',
      'lib.colState': 'Status',
      'lib.empty': 'No books match the filters',
      'lib.summary': 'Showing {shown} / {total}　{noted} with notes',
      'lib.unranked': 'Unranked',
      'lib.hasNote': 'Noted',
      'reader.shelf': 'Shelf',
      'reader.allBooks': 'All books',
      'reader.noNote': 'No notes yet',
      'reader.loading': 'Loading…',
      'reader.back': 'Library',
      'state.pending': 'Queued',
      'state.searching': 'Searching',
      'state.downloading': 'Downloading',
      'state.verifying': 'Verifying',
      'state.noting': 'Writing notes',
      'state.available': 'Ready',
      'state.noted': 'Done',
      'state.unavailable': 'Not found',
      'state.failed': 'Failed',
      'group.noted': 'Noted',
      'group.active': 'In progress',
      'group.unavailable': 'Not found',
      'group.failed': 'Failed',
      'group.pending': 'Not started',
      'prio.0': 'P0 Highest',
      'prio.1': 'P1 Second',
      'prio.2': 'P2 Third',
      'prio.3': 'P3 Fourth',
      'ingest.badge': 'Pawread Reading Desk',
      'ingest.ph': 'Paste book titles, one per line…\nThinking in Systems\n穷查理宝典\nEl principito',
      'ingest.f1t': 'Multilingual',
      'ingest.f1d': 'Chinese, Spanish and German titles are normalised to their English original before searching.',
      'ingest.f2t': 'Complete notes',
      'ingest.f2d': 'Nothing compressed, nothing paraphrased — original quotes kept verbatim.',
      'ingest.f3t': 'Layered reading',
      'ingest.f3d': 'Every note carries a table of contents and a preview of each chapter.',
      'lib.read': 'Read',
      'reader.progress': 'Reading progress',
      'reader.reading': 'Reading',
      'ingest.hint': 'One title per line, up to 100 at a time',
      'ingest.privacy': 'Chinese, Spanish and German titles are normalised to their English original',
      'ingest.search': 'Search title or ID…',
      'ingest.guarantee': 'Reading Assurance & Assistance',
      'ingest.noFile': 'No file yet',
      'ingest.detail': 'View Details',
      'ingest.readNote': 'Read Note',
      'ingest.downloadNote': 'Download Note',
      'ingest.guaranteeDesc': 'Every free-resource lookup and download is logged. Books that cannot be found are marked with a reason in the queue, and you can review all unfinished tasks on the library page.',
      'group.all': 'All',
    },
    es: {
      'nav.ingest': 'Ingesta',
      'nav.library': 'Biblioteca',
      'nav.reader': 'Leer',
      'ingest.title': 'Cola de lectura',
      'ingest.desc': 'Pega títulos de libros, uno por línea, hasta 100 a la vez. Se aceptan chino, inglés, español y alemán — los chinos se traducen al título original en inglés antes de buscar.',
      'ingest.label': 'Títulos de libros',
      'ingest.lang': 'Idioma',
      'ingest.submit': 'Empezar',
      'ingest.queue': 'Cola de proceso',
      'ingest.empty': 'Aún no hay tareas',
      'ingest.emptyHint': 'Pega títulos arriba para empezar',
      'ingest.count': '{n} libros',
      'ingest.submitted': '{n} libros enviados',
      'ingest.maxBooks': 'Hasta 100 libros a la vez',
      'ingest.read': 'Leer',
      'ingest.source': 'Fuente',
      'lib.badge': 'Mi estantería',
      'lib.title': 'Mi biblioteca',
      'lib.desc': 'Filtra por prioridad, haz clic en un libro para leerlo.',
      'lib.all': 'Todos los libros',
      'lib.priority': 'Prioridad',
      'lib.status': 'Estado',
      'lib.search': 'Buscar título o traducción…',
      'lib.colTitle': 'Título',
      'lib.colZh': 'Traducción',
      'lib.colPrio': 'Prioridad',
      'lib.colState': 'Estado',
      'lib.empty': 'Ningún libro coincide con los filtros',
      'lib.summary': 'Mostrando {shown} / {total}　{noted} con notas',
      'lib.unranked': 'Sin prioridad',
      'lib.hasNote': 'Con notas',
      'reader.shelf': 'Estantería',
      'reader.allBooks': 'Todos los libros',
      'reader.noNote': 'Aún no hay notas',
      'reader.loading': 'Cargando…',
      'reader.back': 'Biblioteca',
      'state.pending': 'En cola',
      'state.searching': 'Buscando',
      'state.downloading': 'Descargando',
      'state.verifying': 'Verificando',
      'state.noting': 'Escribiendo notas',
      'state.available': 'Listo',
      'state.noted': 'Hecho',
      'state.unavailable': 'No encontrado',
      'state.failed': 'Falló',
      'group.noted': 'Con notas',
      'group.active': 'En proceso',
      'group.unavailable': 'No encontrado',
      'group.failed': 'Falló',
      'group.pending': 'Sin empezar',
      'prio.0': 'P0 Máxima',
      'prio.1': 'P1 Segunda',
      'prio.2': 'P2 Tercera',
      'prio.3': 'P3 Cuarta',
      'ingest.badge': 'Mesa de lectura Pawread',
      'ingest.ph': 'Pega títulos, uno por línea…\nThinking in Systems\n穷查理宝典\nEl principito',
      'ingest.f1t': 'Multilingüe',
      'ingest.f1d': 'Los títulos chinos, españoles y alemanes se normalizan al original en inglés antes de buscar.',
      'ingest.f2t': 'Notas completas',
      'ingest.f2d': 'Sin comprimir ni parafrasear — las citas originales se conservan textualmente.',
      'ingest.f3t': 'Lectura por capas',
      'ingest.f3d': 'Cada nota incluye un índice y un adelanto de cada capítulo.',
      'lib.read': 'Leer',
      'reader.progress': 'Progreso de lectura',
      'reader.reading': 'Leyendo',
      'ingest.hint': 'Un título por línea, hasta 100 a la vez',
      'ingest.privacy': 'Los títulos chinos, españoles y alemanes se normalizan al original en inglés',
      'ingest.search': 'Buscar título o ID…',
      'ingest.guarantee': 'Garantía de lectura y asistencia',
      'ingest.noFile': 'Aún sin archivo',
      'ingest.detail': 'Ver detalles',
      'ingest.readNote': 'Leer notas',
      'ingest.downloadNote': 'Descargar notas',
      'ingest.guaranteeDesc': 'Cada búsqueda y descarga de recursos gratuitos queda registrada. Los libros no encontrados se marcan con un motivo en la cola, y puedes revisar todas las tareas pendientes en la biblioteca.',
      'group.all': 'Todos',
    },
    de: {
      'nav.ingest': 'Eingabe',
      'nav.library': 'Bibliothek',
      'nav.reader': 'Lesen',
      'ingest.title': 'Leseaufträge',
      'ingest.desc': 'Buchtitel einfügen, einen pro Zeile, bis zu 100 auf einmal. Chinesisch, Englisch, Spanisch und Deutsch werden unterstützt — chinesische Titel werden vor der Suche ins englische Original übersetzt.',
      'ingest.label': 'Buchtitel',
      'ingest.lang': 'Sprache',
      'ingest.submit': 'Starten',
      'ingest.queue': 'Verarbeitungswarteschlange',
      'ingest.empty': 'Noch keine Aufträge',
      'ingest.emptyHint': 'Titel oben einfügen, um zu beginnen',
      'ingest.count': '{n} Bücher',
      'ingest.submitted': '{n} Bücher übermittelt',
      'ingest.maxBooks': 'Bis zu 100 Bücher auf einmal',
      'ingest.read': 'Lesen',
      'ingest.source': 'Quelle',
      'lib.badge': 'Mein Bücherregal',
      'lib.title': 'Meine Bibliothek',
      'lib.desc': 'Nach Priorität filtern, zum Lesen auf ein Buch klicken.',
      'lib.all': 'Alle Bücher',
      'lib.priority': 'Priorität',
      'lib.status': 'Status',
      'lib.search': 'Titel oder Übersetzung suchen…',
      'lib.colTitle': 'Titel',
      'lib.colZh': 'Übersetzung',
      'lib.colPrio': 'Priorität',
      'lib.colState': 'Status',
      'lib.empty': 'Kein Buch entspricht den Filtern',
      'lib.summary': 'Zeige {shown} / {total}　{noted} mit Notizen',
      'lib.unranked': 'Ohne Rang',
      'lib.hasNote': 'Mit Notizen',
      'reader.shelf': 'Regal',
      'reader.allBooks': 'Alle Bücher',
      'reader.noNote': 'Noch keine Notizen',
      'reader.loading': 'Wird geladen…',
      'reader.back': 'Bibliothek',
      'state.pending': 'In Warteschlange',
      'state.searching': 'Suche',
      'state.downloading': 'Download',
      'state.verifying': 'Prüfung',
      'state.noting': 'Notizen werden erstellt',
      'state.available': 'Bereit',
      'state.noted': 'Fertig',
      'state.unavailable': 'Nicht gefunden',
      'state.failed': 'Fehlgeschlagen',
      'group.noted': 'Mit Notizen',
      'group.active': 'In Arbeit',
      'group.unavailable': 'Nicht gefunden',
      'group.failed': 'Fehlgeschlagen',
      'group.pending': 'Nicht begonnen',
      'prio.0': 'P0 Höchste',
      'prio.1': 'P1 Zweite',
      'prio.2': 'P2 Dritte',
      'prio.3': 'P3 Vierte',
      'ingest.badge': 'Pawread Lese-Tisch',
      'ingest.ph': 'Buchtitel einfügen, einer pro Zeile…\nThinking in Systems\n穷查理宝典\nEl principito',
      'ingest.f1t': 'Mehrsprachig',
      'ingest.f1d': 'Chinesische, spanische und deutsche Titel werden vor der Suche ins englische Original normalisiert.',
      'ingest.f2t': 'Vollständige Notizen',
      'ingest.f2d': 'Nichts gekürzt, nichts umgeschrieben — Originalzitate bleiben wörtlich erhalten.',
      'ingest.f3t': 'Gestaffelt lesen',
      'ingest.f3d': 'Jede Notiz enthält ein Inhaltsverzeichnis und eine Vorschau jedes Kapitels.',
      'lib.read': 'Lesen',
      'reader.progress': 'Lesefortschritt',
      'reader.reading': 'Lesend',
      'ingest.hint': 'Ein Titel pro Zeile, bis zu 100 auf einmal',
      'ingest.privacy': 'Chinesische, spanische und deutsche Titel werden ins englische Original normalisiert',
      'ingest.search': 'Titel oder ID suchen…',
      'ingest.guarantee': 'Lese-Sicherung & Unterstützung',
      'ingest.noFile': 'Noch keine Datei',
      'ingest.detail': 'Details ansehen',
      'ingest.readNote': 'Notiz lesen',
      'ingest.downloadNote': 'Notiz herunterladen',
      'ingest.guaranteeDesc': 'Jede Suche und jeder Download kostenloser Ressourcen wird protokolliert. Nicht gefundene Bücher werden in der Warteschlange mit einem Grund markiert, alle offenen Aufgaben siehst du in der Bibliothek.',
      'group.all': 'Alle',
    },
  };

  /** 当前语言。 */
  let current = 'cn';

  /** 取当前语言。 */
  function getLang() { return current; }

  /** 取文案。
   *
   * @param {string} key 键
   * @param {object} [vars] 插值变量
   * @returns {string} 文案
   */
  function t(key, vars) {
    let text = (I18N[current] && I18N[current][key])
            || (I18N.cn[key]) || key;
    if (vars) {
      Object.keys(vars).forEach(k => {
        text = text.replace(new RegExp('\\{' + k + '\\}', 'g'), vars[k]);
      });
    }
    return text;
  }
  /** 应用语言到 DOM。
   *
   * 带 `data-i18n` 的元素替换文本；
   * 带 `data-i18n-ph` 的替换 placeholder；
   * 带 `data-i18n-title` 的替换 title。
   */
  function applyDom(root) {
    const scope = root || document;
    scope.querySelectorAll('[data-i18n]').forEach(el => {
      el.textContent = t(el.dataset.i18n);
    });
    scope.querySelectorAll('[data-i18n-ph]').forEach(el => {
      el.placeholder = t(el.dataset.i18nPh);
    });
    scope.querySelectorAll('[data-i18n-title]').forEach(el => {
      el.title = t(el.dataset.i18nTitle);
    });
  }

  /** 语言按钮的选中态 —— 纯黑胶囊，跟导航一致。 */
  const LANG_ON = 'bg-[#000000] text-white';
  const LANG_OFF = 'text-on-surface-variant hover:text-on-surface';

  /** 更新语言按钮的选中态。
   *
   * @param {string} lang 当前语言
   */
  function paintLangButtons(lang) {
    document.querySelectorAll('#langSwitch button').forEach(b => {
      const on = b.dataset.lang === lang;
      b.classList.toggle('bg-[#000000]', on);
      b.classList.toggle('text-white', on);
      b.classList.toggle('font-semibold', on);
      b.classList.toggle('text-on-surface-variant', !on);
    });
  }

  /** 切换语言。
   *
   * @param {string} lang 语言代码
   * @param {boolean} [reload] 是否刷新页面重新拉数据
   */
  function setLang(lang, reload) {
    if (!I18N[lang]) return;
    current = lang;
    try { localStorage.setItem('pawread:lang', lang); } catch (e) { /* 忽略 */ }
    document.documentElement.lang = lang === 'cn' ? 'zh-CN' : lang;
    applyDom();
    paintLangButtons(lang);
    if (reload !== false) {
      // 书名译名要重新向后端取，刷新最省事
      location.reload();
    }
  }

  /** 初始化。 */
  function init() {
    let saved = null;
    try { saved = localStorage.getItem('pawread:lang'); } catch (e) { /* 忽略 */ }
    current = (saved && I18N[saved]) ? saved : 'cn';
    document.documentElement.lang = current === 'cn' ? 'zh-CN' : current;

    document.querySelectorAll('#langSwitch button').forEach(b => {
      b.addEventListener('click', () => {
        if (b.dataset.lang !== current) setLang(b.dataset.lang, true);
      });
    });
    paintLangButtons(current);

    applyDom();
  }

  window.PawreadI18n = { t, setLang, getLang, applyDom };

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();