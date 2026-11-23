// Промер DOM собранной страницы: что на самом деле стоит в кадре в момент t.
//   node engine/video/probe_dom.mjs <out/фильм>   →   <out/фильм>/probe.json
//
// Открывает index.html в том же headless Chrome, что и HyperFrames, и ставит время тем же путём,
// что рендер: seek GSAP-таймлайна window.__timelines.main. Моменты — из film.json: края и середины
// реплик, биты + 0,7 с, оба кадра каждого стыка, сетка каждые 0,5 с, probe_times (до / начало /
// середина / конец событий, кадры полётов move) и КАЖДЫЙ кадр паузы стыка — от конца последней
// реплики N до 0,5 с после первой N+1.
// В каждый момент: элементы содержания (.el) и каркаса (.fr) — рамка, итоговая непрозрачность, z, слой,
// поворот и масштаб, строки надписей (segs: рамка строки, непрозрачность держателя, едет ли узел move),
// заливки (fills); якоря move (рамка, цвет); трекер глав (видимая часть заливки) и его подписи (trlab);
// голос (цвет подписи, высоты полосок); спутники (sats: рамка спутника в системе своей надписи —
// обратная матрица хозяина из вычисленных transform DOM, а не из рантайма; own — спутник сам едет или звенит);
// цвет целей вспышки; промер плагинов (plugins); конечности героев (limbs: узлы data-limb="<герой>:<сторона>:<up|down>"
// и виден ли каждый — условие позы V25). Один раз: статус каждого @font-face (fonts), рамки
// элементов без трансформаций (els0), части видов (kinds), move (рамка якоря и цели), levelTrace —
// каждый кадр окна каждого уровня (непрозрачность держателей текста), правило округления (round_rule).
// Проверка читает только этот файл.
// Сервер страницы, Chrome (chromePath() из chrome_path.mjs), ожидание шрифтов и таймлайна — общий модуль probe_page.mjs.
import { readFileSync, writeFileSync } from 'node:fs';
import { join, resolve } from 'node:path';
import { serve, launch, openPage } from './probe_page.mjs';      // страница для промера — одно правило на все промеры

const outDir = resolve(process.argv[2] || '.');
const film = JSON.parse(readFileSync(join(outDir, 'film.json'), 'utf8'));
const fps = film.fps;
// ОДНО правило округления времени в кадр на промер, сборку и проверку: floor(t*fps + 0,5 + 0,005).
const frameOf = (t) => Math.floor(t * fps + 0.5 + 5e-3);
const q = (t) => Math.max(0, Math.min(film.duration - 1 / fps, frameOf(t) / fps));

const times = new Set();
for (const r of film.replies) for (const t of [r.start + 2 / fps, (r.start + r.end) / 2, r.end - 2 / fps]) times.add(q(t));
for (const t of film.beat_times) times.add(q(t + 0.7));
const seams = [];
for (let i = 0; i + 1 < film.scenes.length; i++) {
  const a = q(film.scenes[i].end - 1 / fps), b = q(film.scenes[i].end);
  seams.push({ from: film.scenes[i].id, to: film.scenes[i + 1].id, last: a, first: b });
  times.add(a); times.add(b);
}
for (let t = 0; t < film.duration; t += 0.5) times.add(q(t));
for (const t of film.probe_times || []) times.add(q(t));
for (const s of film.scenes) { times.add(q(s.last)); times.add(q(s.last - 1 / fps)); }
for (let i = 0; i + 1 < film.scenes.length; i++) {
  const a = film.scenes[i].last, b = film.scenes[i + 1].first + 0.5;
  for (let f = Math.floor(a * fps); f <= Math.ceil(b * fps); f++) times.add(q(f / fps));
}
const list = [...times].sort((a, b) => a - b);

const { server, url } = await serve(outDir);
const browser = await launch();
try {
  const errors = [];
  const page = await openPage(browser, url, film.canvas, { errors,
    listen: (pg) => pg.on('requestfailed', (r) => errors.push('request failed: ' + r.url())) });
  // статус каждого @font-face: шрифт проекта обязан быть loaded (файл, который Chrome отверг, — error)
  const fonts = await page.evaluate(() => [...document.fonts].map((f) => ({
    family: f.family.replace(/^["']|["']$/g, ''), weight: f.weight, status: f.status })));
  const samples = await page.evaluate((list, moves, sats, flashes) => {
    const F = window.__FILM__, tl = window.__timelines.main;
    const root0 = document.getElementById('root').getBoundingClientRect();
    const rel = (r) => ({ left: r.left - root0.left, top: r.top - root0.top, width: r.width, height: r.height });
    const r4 = (r) => [r.left, r.top, r.width, r.height].map((v) => Math.round(v * 100) / 100);
    function nodeOf(m) { const host = document.getElementById(m.dom); return m.part ? host.querySelector('[data-part="' + m.part + '"]') : host; }
    function texts(n) {
      const w = document.createTreeWalker(n, NodeFilter.SHOW_TEXT, null), out = [];
      let x; while ((x = w.nextNode())) if (x.nodeValue.length) out.push(x);
      return out;
    }
    function range(n, sub, nth) {
      const tn = texts(n);
      if (!tn.length) return null;
      const whole = tn.map((x) => x.nodeValue).join('');
      let from = 0, to = whole.length;
      if (sub != null) {
        let at = -1;
        for (let k = 0; k < (nth || 1); k++) { at = whole.indexOf(sub, at + 1); if (at < 0) return null; }
        from = at; to = at + sub.length;
      } else {
        while (from < to && /\s/.test(whole[from])) from++;
        while (to > from && /\s/.test(whole[to - 1])) to--;
      }
      const rg = document.createRange();
      let pos = 0, started = false, ended = false;
      for (const x of tn) {
        const len = x.nodeValue.length;
        if (!started && from < pos + len) { rg.setStart(x, from - pos); started = true; }
        if (!ended && to > pos && to <= pos + len) { rg.setEnd(x, to - pos); ended = true; }
        pos += len;
      }
      return rg;
    }
    function anchorRect(n, fit) { const rg = fit === 'text' ? range(n) : null; return r4(rel((rg || n).getBoundingClientRect())); }
    function bare(nodes, fn) {       // без трансформаций: узел и все предки до #root
      const saved = [];
      for (const n0 of nodes) for (let n = n0; n && n.id !== 'root'; n = n.parentElement) { saved.push([n, n.style.transform]); n.style.transform = 'none'; }
      try { return fn(); } finally { for (const [n, v] of saved.reverse()) n.style.transform = v; }
    }
    function matrixOf(el) {
      const m = /matrix\(([^)]+)\)/.exec(getComputedStyle(el).transform || '');
      if (!m) return { rot: 0, scale: 1 };
      const [a, b] = m[1].split(',').map(Number);
      return { rot: Math.round(Math.atan2(b, a) * 180 / Math.PI * 100) / 100, scale: Math.round(Math.hypot(a, b) * 10000) / 10000 };
    }
    function opacityOf(el) {
      let o = 1;
      for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
        const cs = getComputedStyle(n);
        if (cs.display === 'none' || cs.visibility === 'hidden') return 0;
        o *= parseFloat(cs.opacity);
        const fo = /opacity\(([\d.]+)\)/.exec(cs.filter || '');     // множитель надписи в тени насыщенного блока
        if (fo) o *= parseFloat(fo[1]);
      }
      return o;
    }
    tl.totalTime(0, false);
    const moveInfo = moves.map((m) => {
      const n = nodeOf(m), dn = m.dest.dom ? document.getElementById(m.dest.dom) : null;
      return bare([n].concat(dn ? [dn] : []), () => {
        let dest = null;
        if (m.dest.kind === 'box') dest = m.dest.box;
        else if (m.dest.kind === 'el') dest = r4(rel(dn.getBoundingClientRect()));
        else { const rg = range(dn, m.dest.sub, m.dest.nth); dest = rg ? r4(rel(rg.getBoundingClientRect())) : null; }
        const tn = texts(n);
        return { node: m.node, t: m.t, anchor0: anchorRect(n, m.fit), dest,
          fontPx: tn.length ? parseFloat(getComputedStyle(tn[0].parentNode).fontSize) : 0 };
      });
    });
    const movers = [...new Set(moves.map((m) => m.node))].map((k) => [k, moves.find((m) => m.node === k)]);
    const moverEls = movers.map(([, m]) => nodeOf(m)).filter(Boolean);
    // части видов — один раз, без трансформаций (контракт видов)
    const kinds = {};
    document.querySelectorAll('.el[class*="k-"]').forEach((el) => bare([el], () => {
      const parts = {};
      el.querySelectorAll('[data-part], .step-num, .qz-answer').forEach((n) => {
        const cs = getComputedStyle(n), tn = texts(n);
        let line = null;
        if (tn.length) {
          const rg = document.createRange(); rg.selectNodeContents(n);
          const rs = [...rg.getClientRects()].filter((r) => r.width > 0.5 && r.height > 0.5);
          if (rs.length) line = r4(rel(rs[0]));
        }
        parts[n.dataset.part || n.className] = { rect: r4(rel(n.getBoundingClientRect())), fontPx: parseFloat(cs.fontSize),
          fontWeight: cs.fontWeight, color: cs.color, bg: cs.backgroundColor, border: parseFloat(cs.borderTopWidth) || 0,
          borderColor: cs.borderTopColor, shadow: cs.boxShadow, display: cs.display, line };
      });
      const cs = getComputedStyle(el);
      kinds[el.id] = { kind: [...el.classList].find((c) => c.startsWith('k-')), rect: r4(rel(el.getBoundingClientRect())),
        bg: cs.backgroundColor, color: cs.color, shadow: cs.boxShadow, parts };
    }));
    // каркас один раз: цвет и кегль заголовка, футера, номера, линий, плашек трекера (сверка с tokens.json)
    const frameStyle = {};
    document.querySelectorAll('.fr').forEach((n) => {
      const cs = getComputedStyle(n);
      frameStyle[n.id] = { color: cs.color, bg: cs.backgroundColor, fontPx: parseFloat(cs.fontSize), fontWeight: cs.fontWeight,
        fontFamily: cs.fontFamily, synthesis: getComputedStyle(document.getElementById('root')).fontSynthesis };
    });
    // синтез начертаний корня — и у страницы без каркаса (сцены frame: false): V11 смотрит его, когда .fr нет
    const rootStyle = { synthesis: getComputedStyle(document.getElementById('root')).fontSynthesis };
    const fillNodes = new Map();
    document.querySelectorAll('.el').forEach((el) => {
      const lst = [];
      [el, ...el.querySelectorAll('*')].forEach((n) => {
        if (n instanceof SVGElement) return;
        const m = /rgba?\(([\d.]+),\s*([\d.]+),\s*([\d.]+)(?:,\s*([\d.]+))?/.exec(getComputedStyle(n).backgroundColor || '');
        if (!m || (m[4] != null && parseFloat(m[4]) === 0)) return;
        lst.push([n, 'rgb(' + m[1] + ', ' + m[2] + ', ' + m[3] + ')']);
      });
      if (lst.length) fillNodes.set(el, lst);
    });
    const trLabs = [...document.querySelectorAll('.tr-lab')];
    function layoutPos(n) { let x = 0, y = 0; for (let a = n; a && a.id !== 'root'; a = a.offsetParent) { x += a.offsetLeft; y += a.offsetTop; } return [x, y]; }
    function absMatrix(n) {
      const chain = []; for (let a = n; a && a.id !== 'root'; a = a.parentElement) chain.unshift(a);
      let m = new DOMMatrix();
      for (const a of chain) {
        const cs = getComputedStyle(a);
        if (!cs.transform || cs.transform === 'none') continue;
        const o = cs.transformOrigin.split(' ').map(parseFloat), l = layoutPos(a);
        m = m.translate(l[0] + o[0], l[1] + o[1]).multiply(new DOMMatrix(cs.transform)).translate(-(l[0] + o[0]), -(l[1] + o[1]));
      }
      return m;
    }
    function hostAt(s, t) { let h = null; for (const b of s.follow) if (b.t == null || b.t <= t + 1e-6) h = b.host; return h; }
    const elByDom = {};
    for (const e of F.elements) if (!e.part) elByDom[e.dom] = e;
    function ownMotion(dom, t) {     // спутник сам едет (свой move) или у него свой emph — C19 его не мерит
      const e = elByDom[dom];
      if (!e) return false;
      const ad = F.motion.anim_dur;      // свой вход pop масштабирует спутник сам (сдвиг rise / lift он берёт у хозяина)
      return e.moves.some((m) => t >= m.t - 1e-6 && t <= m.t + m.dur + 1e-6)
        || e.emph.some((m) => t >= m.t - 1e-6 && t <= m.t + m.dur + 1e-6)
        || e.events.some((v) => v.anim === 'pop' && t >= v.t - 1e-6 && t <= v.t + (v.dur != null ? v.dur : ad.pop) + 1e-6);
    }
    function satRecord(s, t) {
      const host = hostAt(s, t), n = document.getElementById(s.dom), hn = host && document.getElementById(host);
      if (!n || !hn) return null;
      const hm = absMatrix(hn);
      const r = rel(n.getBoundingClientRect()), inv = hm.inverse();
      const pts = [[r.left, r.top], [r.left + r.width, r.top], [r.left, r.top + r.height], [r.left + r.width, r.top + r.height]]
        .map(([x, y]) => inv.transformPoint(new DOMPoint(x, y)));
      const xs = pts.map((p) => p.x), ys = pts.map((p) => p.y);
      const l = Math.min(...xs), tp = Math.min(...ys);
      return { host, local: r4({ left: l, top: tp, width: Math.max(...xs) - l, height: Math.max(...ys) - tp }),
        op: Math.round(opacityOf(n) * 1000) / 1000, hop: Math.round(opacityOf(hn) * 1000) / 1000,
        hostScale: Math.round(Math.hypot(hm.a, hm.b) * 10000) / 10000,
        hostShift: Math.round(Math.hypot(hm.e, hm.f) * 100) / 100, own: ownMotion(s.dom, t) };
    }
    function dashOf(el) {
      const sh = el.querySelector('svg path, svg line, svg polyline, svg polygon, svg circle, svg ellipse, svg rect');
      if (!sh) return null;
      const cs = getComputedStyle(sh);
      return cs.strokeDasharray && cs.strokeDasharray !== 'none' ? Math.round(parseFloat(cs.strokeDashoffset) * 1000) / 1000 : null;
    }
    const out = [];
    for (const t of list) {
      tl.totalTime(t, false);
      const items = [];
      document.querySelectorAll('.el, .fr').forEach((el) => {
        const o = opacityOf(el);
        if (o <= 0.001) return;
        const mx = matrixOf(el);
        const segs = [];
        el.querySelectorAll('.t').forEach((tnode) => {
          for (const x of texts(tnode)) {
            if (!x.nodeValue.trim()) continue;
            const holder = x.parentNode, op = Math.round(opacityOf(holder) * 1000) / 1000;
            if (op <= 0.001) continue;
            const mv = moverEls.some((m) => m.contains(holder)) ? 1 : 0;
            const rg = document.createRange();
            rg.selectNodeContents(x);
            for (const r of rg.getClientRects()) {
              if (r.width < 0.5 || r.height < 0.5) continue;
              segs.push(r4(rel(r)).concat([op, mv]));
            }
          }
        });
        const fills = [];
        for (const [n, col] of fillNodes.get(el) || []) {
          const r = n.getBoundingClientRect();
          if (r.width * r.height < 100) continue;
          const fo = Math.round(opacityOf(n) * 1000) / 1000;
          if (fo > 0.001) fills.push(r4(rel(r)).concat([fo, col]));
        }
        items.push({ id: el.id, kind: el.classList.contains('el') ? 'content' : 'frame', segs, fills,
          scene: el.getAttribute('data-scene') || null, rect: r4(rel(el.getBoundingClientRect())),
          opacity: Math.round(o * 1000) / 1000, z: parseInt(getComputedStyle(el).zIndex, 10) || 0,
          layer: el.getAttribute('data-layer') || null, rot: mx.rot, scale: mx.scale, cam: !!el.closest('.cam'),
          dash: el.classList.contains('k-icon') ? dashOf(el) : null,
          texts: [...el.querySelectorAll('.t')].map((n) => n.textContent.replace(/\s+/g, ' ').trim()) });
      });
      const anchors = {};
      for (const [k, m] of movers) {
        const n = nodeOf(m);
        anchors[k] = { rect: anchorRect(n, m.fit), color: getComputedStyle(n).color,
          opacity: Math.round(opacityOf(n) * 1000) / 1000, rot: matrixOf(n).rot };
      }
      const tracker = [...document.querySelectorAll('.tr-on')].map((n) => {
        const r = rel(n.getBoundingClientRect()), cp = /inset\(([^)]+)\)/.exec(getComputedStyle(n).clipPath || '');
        let l = r.left, rr = r.left + r.width;
        if (cp) { const v = cp[1].split(/\s+/).map(parseFloat); l += v[3] || 0; rr -= v[1] || 0; }
        return { id: n.id, opacity: Math.round(opacityOf(n) * 1000) / 1000, fill: [Math.round(l * 100) / 100, Math.round(rr * 100) / 100] };
      });
      const voice = {};
      document.querySelectorAll('.fr-voice').forEach((g) => {
        voice[g.dataset.voice] = { name: getComputedStyle(g.querySelector('.vo-name')).color,
          bars: [...g.querySelectorAll('.vo-bar')].map((b) => Math.round(b.getBoundingClientRect().height * 100) / 100),
          barColor: getComputedStyle(g.querySelector('.vo-bar')).backgroundColor };
      });
      const trlab = trLabs.map((n) => {
        const rg = document.createRange(); rg.selectNodeContents(n);
        return r4(rel(rg.getBoundingClientRect())).concat([Math.round(opacityOf(n) * 1000) / 1000]);
      }).filter((x) => x[4] > 0.001);
      const root = document.getElementById('root');
      const flash = {};
      for (const m of flashes) { const n = nodeOf(m); if (n) flash[m.node] = getComputedStyle(n).color; }
      const satRec = {};
      for (const s of sats) { const r = satRecord(s, t); if (r) satRec[s.node] = r; }
      const plugins = (window.__stage.plugins || []).map((p) => (p && p.probe ? p.probe(t) : null));
      const limbs = [...document.querySelectorAll('[data-limb]')].map((n) => {
        const [who, side, pos] = (n.getAttribute('data-limb') || '').split(':');
        const el = n.closest('.el'), sec = n.closest('.scene'), bb = n.getBoundingClientRect();
        return { who: who || null, side: side || null, pos: pos || null, el: el ? el.id : null,
          scene: sec ? sec.dataset.scene : (el ? el.getAttribute('data-scene') : null),
          seen: opacityOf(n) > 0.02 && bb.width + bb.height > 0 };
      });
      out.push({ t, scene: root.dataset.scene, reply: root.dataset.reply ? Number(root.dataset.reply) : null,
        items, anchors, tracker, trlab, voice, sats: satRec, flash, plugins, limbs });
    }
    tl.totalTime(0, false);
    const els0 = {};
    document.querySelectorAll('.el').forEach((el) => bare([el], () => {
      els0[el.id] = { rect: r4(rel(el.getBoundingClientRect())), scene: el.getAttribute('data-scene'), layer: el.getAttribute('data-layer'),
        text: [...el.querySelectorAll('.t')].some((n) => n.textContent.trim()), icon: !!el.querySelector('svg'),
        lines: [...el.querySelectorAll('.t')].flatMap((n) => texts(n).filter((x) => x.nodeValue.trim()).flatMap((x) => {
          const rg = document.createRange(); rg.selectNodeContents(x);
          return [...rg.getClientRects()].filter((r) => r.width > 0.5 && r.height > 0.5).map((r) => r4(rel(r)));
        })),
        parent: el.parentElement && el.parentElement.id };
    }));
    const layers = [...document.querySelectorAll('#root > .layer')].map((n) => n.id);
    return { out, moveInfo, kinds, els0, frameStyle, rootStyle, layers };
  }, list, film.moves || [], film.sats || [], film.flashes || []);
  // смена уровня (условие V14): КАЖДЫЙ кадр окна каждого уровня с длительностью — непрозрачность держателей текста узла
  const levelTrace = await page.evaluate((fps, dur) => {
    const F = window.__FILM__, tl = window.__timelines.main;
    const fr = (t) => Math.floor(t * fps + 0.5 + 5e-3), last = Math.floor(dur * fps) - 1;
    function opacityOf(el) {
      let o = 1;
      for (let n = el; n && n.nodeType === 1; n = n.parentElement) {
        const cs = getComputedStyle(n);
        if (cs.display === 'none' || cs.visibility === 'hidden') return 0;
        o *= parseFloat(cs.opacity);
        const fo = /opacity\(([\d.]+)\)/.exec(cs.filter || '');
        if (fo) o *= parseFloat(fo[1]);
      }
      return o;
    }
    const out = [];
    for (const e of F.elements) {
      const wins = [];
      for (const lv of e.levels) { if (lv.dur > 0) wins.push([Math.max(0, fr(lv.t) - 1), Math.min(last, fr(lv.t + lv.dur) + 2)]); }
      if (!wins.length) continue;
      const host = document.getElementById(e.dom), node = e.part ? host.querySelector('[data-part="' + e.part + '"]') : host;
      const w = document.createTreeWalker(node, NodeFilter.SHOW_TEXT, null), holders = [];
      let x; while ((x = w.nextNode())) if (x.nodeValue.trim() && holders.indexOf(x.parentNode) < 0) holders.push(x.parentNode);
      if (!holders.length) continue;
      wins.sort((a, b) => a[0] - b[0]);
      const merged = [];
      for (const v of wins) { const m = merged[merged.length - 1]; if (m && v[0] <= m[1] + 1) m[1] = Math.max(m[1], v[1]); else merged.push(v.slice()); }
      for (const [f0, f1] of merged) {
        const ops = [];
        for (let f = f0; f <= f1; f++) { tl.totalTime(f / fps, false); ops.push(holders.map((h) => Math.round(opacityOf(h) * 1000) / 1000)); }
        out.push({ dom: e.dom, part: e.part || null, f0, ops });
      }
    }
    return out;
  }, fps, film.duration);
  writeFileSync(join(outDir, 'probe.json'), JSON.stringify({ film: film.film, fps, duration: film.duration,
    els0: samples.els0, layers: samples.layers, frameStyle: samples.frameStyle, rootStyle: samples.rootStyle,
    round_rule: [...Array(12).keys()].flatMap((k) => [k, k + 60]).map((k) => [(k + 0.5) / fps, q((k + 0.5) / fps)]),
    seams, errors, fonts, levelTrace, moves: samples.moveInfo, kinds: samples.kinds, samples: samples.out }, null, 0));
  if (errors.length) { console.error('Ошибки страницы:\n' + errors.join('\n')); process.exitCode = 1; }
} finally {
  await browser.close();
  server.close();
}
