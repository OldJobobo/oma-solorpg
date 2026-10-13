// oma-solorpg's page. No framework and no build: the same moments the plugin has (titles
// that decrypt, a d20 that tumbles and lands, a face that follows the story, a desktop that
// flashes gold for a Dragon), made again for a browser.
(function () {
  "use strict";

  var $ = function (s, r) { return (r || document).querySelector(s); };
  var $$ = function (s, r) { return Array.prototype.slice.call((r || document).querySelectorAll(s)); };
  var reduced = window.matchMedia && matchMedia("(prefers-reduced-motion: reduce)").matches;
  var ART = window.OMA_ART || { heroes: {}, sprites: {}, faces: {} };

  // Per-viewer settings only (theme, sound). Private windows may refuse storage: that's fine.
  var store = {
    get: function (k) { try { return localStorage.getItem(k); } catch (e) { return null; } },
    set: function (k, v) { try { localStorage.setItem(k, v); } catch (e) { /* no storage */ } }
  };
  function wait(ms) { return new Promise(function (r) { setTimeout(r, ms); }); }
  function esc(s) { return String(s).replace(/[&<>"]/g, function (c) { return { "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]; }); }
  function d20() { return 1 + Math.floor(Math.random() * 20); }

  // Sound: made on the spot, as the plugin makes its own ------------------------------

  var Sound = (function () {
    var ctx = null, master = null;
    var on = store.get("oma-sound") !== "off";

    function ac() {
      if (!ctx) {
        var C = window.AudioContext || window.webkitAudioContext;
        if (!C) return null;
        ctx = new C();
        master = ctx.createDynamicsCompressor();
        var gain = ctx.createGain();
        gain.gain.value = 0.55;
        master.connect(gain);
        gain.connect(ctx.destination);
      }
      if (ctx.state === "suspended") ctx.resume();
      return ctx;
    }
    function noise(c, seconds) {
      var buffer = c.createBuffer(1, Math.max(1, Math.floor(c.sampleRate * seconds)), c.sampleRate);
      var data = buffer.getChannelData(0);
      for (var i = 0; i < data.length; i++) data[i] = Math.random() * 2 - 1;
      var src = c.createBufferSource();
      src.buffer = buffer;
      return src;
    }
    function env(g, t, attack, peak, decay) {
      g.gain.setValueAtTime(0.0001, t);
      g.gain.exponentialRampToValueAtTime(peak, t + attack);
      g.gain.exponentialRampToValueAtTime(0.0001, t + attack + decay);
    }
    function tone(c, t, type, freq, to, attack, peak, decay, dest) {
      var o = c.createOscillator(), g = c.createGain();
      o.type = type;
      o.frequency.setValueAtTime(freq, t);
      if (to) o.frequency.exponentialRampToValueAtTime(to, t + attack + decay);
      env(g, t, attack, peak, decay);
      o.connect(g); g.connect(dest || master);
      o.start(t); o.stop(t + attack + decay + 0.05);
    }
    function burst(c, t, filter, freq, q, peak, decay) {
      var n = noise(c, decay + 0.05), f = c.createBiquadFilter(), g = c.createGain();
      f.type = filter; f.frequency.value = freq; f.Q.value = q || 1;
      env(g, t, 0.003, peak, decay);
      n.connect(f); f.connect(g); g.connect(master);
      n.start(t); n.stop(t + decay + 0.05);
    }

    var voices = {
      // A die on the table: clicks that slow down the way the Book's tumble does.
      dice: function (c, t) {
        var at = t;
        for (var i = 0; i < 12; i++) {
          burst(c, at, "bandpass", 2200 + Math.random() * 2600, 3, 0.35 - i * 0.02, 0.035);
          at += (45 + i * i * 1.6) / 1000;
        }
      },
      land: function (c, t) {
        tone(c, t, "sine", 150, 55, 0.004, 0.7, 0.22);
        burst(c, t, "bandpass", 1800, 2, 0.4, 0.06);
      },
      chime: function (c, t) {
        [880, 1318.5, 1760, 2637].forEach(function (f, i) {
          tone(c, t + i * 0.06, "sine", f, 0, 0.005, 0.22 / (i + 1), 2.6 - i * 0.3);
          tone(c, t + i * 0.06, "sine", f * 1.003, 0, 0.005, 0.08 / (i + 1), 2.2);
        });
      },
      growl: function (c, t) {
        var o = c.createOscillator(), lfo = c.createOscillator(), depth = c.createGain(), f = c.createBiquadFilter(), g = c.createGain();
        o.type = "sawtooth"; o.frequency.setValueAtTime(72, t); o.frequency.linearRampToValueAtTime(54, t + 1.3);
        lfo.frequency.value = 9; depth.gain.value = 0.25;
        f.type = "lowpass"; f.frequency.value = 420;
        env(g, t, 0.08, 0.5, 1.3);
        lfo.connect(depth); depth.connect(g.gain);
        o.connect(f); f.connect(g); g.connect(master);
        o.start(t); lfo.start(t); o.stop(t + 1.5); lfo.stop(t + 1.5);
        burst(c, t, "lowpass", 300, 1, 0.3, 1.1);
      },
      hit: function (c, t) {
        tone(c, t, "sine", 160, 40, 0.003, 0.9, 0.3);
        burst(c, t, "lowpass", 900, 1, 0.6, 0.18);
      },
      drum: function (c, t) {
        [0, 0.34, 0.52, 0.86].forEach(function (d, i) {
          tone(c, t + d, "sine", i === 3 ? 110 : 92, 42, 0.004, i === 3 ? 0.95 : 0.8, 0.45);
          burst(c, t + d, "lowpass", 500, 1, 0.35, 0.12);
        });
      },
      bell: function (c, t) {
        [0.5, 1, 1.19, 1.56, 2, 2.51, 2.66, 3.01].forEach(function (r, i) {
          tone(c, t, "sine", 196 * r, 0, 0.004, 0.3 / (1 + i * 0.6), 5.5 - i * 0.45);
        });
      },
      heart: function (c, t) {
        tone(c, t, "sine", 62, 45, 0.01, 0.9, 0.16);
        tone(c, t + 0.24, "sine", 58, 42, 0.01, 0.65, 0.2);
      },
      torch: function (c, t) {
        burst(c, t, "bandpass", 700, 0.7, 0.35, 0.9);
        for (var i = 0; i < 7; i++) burst(c, t + 0.15 + Math.random() * 0.8, "highpass", 3000, 1, 0.25, 0.02);
      },
      page: function (c, t) {
        var n = noise(c, 0.5), f = c.createBiquadFilter(), g = c.createGain();
        f.type = "bandpass"; f.Q.value = 0.8;
        f.frequency.setValueAtTime(900, t); f.frequency.exponentialRampToValueAtTime(4200, t + 0.35);
        env(g, t, 0.06, 0.25, 0.35);
        n.connect(f); f.connect(g); g.connect(master); n.start(t); n.stop(t + 0.5);
      },
      omen: function (c, t) {
        tone(c, t, "sine", 110, 0, 0.6, 0.25, 2.4);
        tone(c, t, "sine", 113.2, 0, 0.6, 0.22, 2.4);
        tone(c, t, "triangle", 55, 0, 0.8, 0.2, 2.2);
      },
      scene: function (c, t) {
        tone(c, t, "sine", 220, 0, 0.4, 0.12, 2.2);
        tone(c, t + 0.1, "sine", 330, 0, 0.4, 0.08, 2);
      }
    };

    function play(name, delay) {
      if (!on || !voices[name]) return;
      var c = ac();
      if (!c) return;
      try { voices[name](c, c.currentTime + 0.02 + (delay || 0)); } catch (e) { /* a browser without some node: stay quiet */ }
    }
    return {
      play: play,
      get on() { return on; },
      set: function (v) { on = !!v; store.set("oma-sound", on ? "on" : "off"); }
    };
  })();

  // Themes: Omarchy's, picked the way Omarchy picks them -------------------------------

  var THEMES = [
    ["tokyo-night", "Tokyo Night", ["#1a1b26", "#7aa2f7", "#e0af68", "#f7768e"]],
    ["catppuccin", "Catppuccin", ["#1e1e2e", "#89b4fa", "#f9e2af", "#f38ba8"]],
    ["catppuccin-latte", "Catppuccin Latte", ["#eff1f5", "#1e66f5", "#9a5f07", "#d20f39"]],
    ["gruvbox", "Gruvbox", ["#282828", "#83a598", "#fabd2f", "#fb4934"]],
    ["nord", "Nord", ["#2e3440", "#88c0d0", "#ebcb8b", "#bf616a"]],
    ["everforest", "Everforest", ["#2d353b", "#a7c080", "#dbbc7f", "#e67e80"]],
    ["kanagawa", "Kanagawa", ["#1f1f28", "#7e9cd8", "#e6c384", "#ff5d62"]],
    ["rose-pine", "Rosé Pine", ["#191724", "#c4a7e7", "#f6c177", "#eb6f92"]],
    ["matte-black", "Matte Black", ["#121212", "#e68e0d", "#f0b429", "#d35f5f"]]
  ];
  function themeName(id) { var t = THEMES.filter(function (x) { return x[0] === id; })[0]; return t ? t[1] : THEMES[0][1]; }
  function applyTheme(id, keep) {
    if (!THEMES.some(function (t) { return t[0] === id; })) id = THEMES[0][0];
    document.documentElement.dataset.omaTheme = id;
    $("#theme-name").textContent = themeName(id);
    var meta = $('meta[name="theme-color"]');
    if (meta) meta.content = getComputedStyle(document.documentElement).getPropertyValue("--bar").trim() || "#16161e";
    if (keep) store.set("oma-theme", id);
  }

  function walker() {
    var dialog = $("#walker"), input = $("#walker-q"), list = $("#walker-list");
    if (!dialog || typeof dialog.showModal !== "function") return;
    var chosen = document.documentElement.dataset.omaTheme, index = 0, shown = [];
    function render() {
      var q = input.value.trim().toLowerCase();
      shown = THEMES.filter(function (t) { return t[1].toLowerCase().indexOf(q) !== -1; });
      index = Math.max(0, Math.min(index, shown.length - 1));
      list.innerHTML = shown.map(function (t, i) {
        return '<li role="option" data-id="' + t[0] + '" aria-selected="' + (i === index) + '"><span class="sw">' +
          t[2].map(function (c) { return '<i style="background:' + c + '"></i>'; }).join("") + "</span>" + esc(t[1]) +
          (t[0] === chosen ? '<span class="cur">current</span>' : "") + "</li>";
      }).join("");
      if (shown[index]) applyTheme(shown[index][0], false);
    }
    function pick() {
      if (shown[index]) { chosen = shown[index][0]; applyTheme(chosen, true); }
      dialog.close("picked");
    }
    $("#theme-btn").addEventListener("click", function () {
      chosen = document.documentElement.dataset.omaTheme;
      input.value = "";
      index = Math.max(0, THEMES.findIndex(function (t) { return t[0] === chosen; }));
      render();
      dialog.showModal();
      input.focus();
    });
    input.addEventListener("input", function () { index = 0; render(); });
    dialog.addEventListener("keydown", function (e) {
      if (e.key === "ArrowDown") { index = (index + 1) % Math.max(1, shown.length); render(); e.preventDefault(); }
      else if (e.key === "ArrowUp") { index = (index - 1 + shown.length) % Math.max(1, shown.length); render(); e.preventDefault(); }
      else if (e.key === "Enter") { e.preventDefault(); pick(); }
    });
    list.addEventListener("click", function (e) {
      var li = e.target.closest("li");
      if (!li) return;
      index = shown.findIndex(function (t) { return t[0] === li.dataset.id; });
      pick();
    });
    list.addEventListener("mousemove", function (e) {
      var li = e.target.closest("li");
      if (!li) return;
      var i = shown.findIndex(function (t) { return t[0] === li.dataset.id; });
      if (i !== index) { index = i; render(); }
    });
    dialog.addEventListener("close", function () {
      if (dialog.returnValue !== "picked") applyTheme(chosen, false);
      dialog.returnValue = "";
    });
    dialog.addEventListener("click", function (e) { if (e.target === dialog) dialog.close(); });
  }

  // The bar: clock, workspaces, sound, the d20 -----------------------------------------

  function clock() {
    var el = $("#clock");
    function tick() {
      var d = new Date();
      el.textContent = d.toLocaleDateString("en-US", { weekday: "long" }) + " " +
        String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0");
    }
    tick();
    setInterval(tick, 15000);
  }

  function workspaces() {
    var links = $$(".workspaces a[data-ws]");
    var sections = $$("section[data-ws]");
    var title = $("#bar-title"), shown = null;
    // The window title beside the numbers, the way waybar shows the focused window's.
    function mark(ws) {
      links.forEach(function (a) { a.classList.toggle("active", a.dataset.ws === ws); });
      var link = links.filter(function (a) { return a.dataset.ws === ws; })[0];
      if (!title || !link || shown === ws) return;
      shown = ws;
      title.classList.add("swap");
      setTimeout(function () { title.textContent = link.title; title.classList.remove("swap"); }, reduced ? 0 : 160);
    }
    if ("IntersectionObserver" in window) {
      var io = new IntersectionObserver(function (entries) {
        entries.forEach(function (e) { if (e.isIntersecting) mark(e.target.dataset.ws); });
      }, { rootMargin: "-40% 0px -55% 0px" });
      sections.forEach(function (s) { io.observe(s); });
    }
    mark("1");
    // SUPER+1..8 on Omarchy; here the digits alone, as long as nothing is being typed.
    document.addEventListener("keydown", function (e) {
      if (e.ctrlKey || e.metaKey || e.altKey || /INPUT|TEXTAREA|SELECT/.test((e.target || {}).tagName || "")) return;
      if (document.querySelector("dialog[open]") || document.documentElement.classList.contains("secret-open")) return;
      var n = parseInt(e.key, 10);
      var target = sections.filter(function (s) { return s.dataset.ws === String(n); })[0];
      if (target) { target.scrollIntoView({ behavior: reduced ? "auto" : "smooth" }); e.preventDefault(); }
    });
  }

  function soundButton() {
    var b = $("#sound-btn");
    function show() { b.setAttribute("aria-pressed", String(Sound.on)); b.title = Sound.on ? "Sound on" : "Sound off"; }
    show();
    b.addEventListener("click", function () { Sound.set(!Sound.on); show(); if (Sound.on) Sound.play("page"); });
  }

  function barDie() {
    var b = $("#bar-d20"), out = $("#bar-roll"), timer = null;
    b.addEventListener("click", function () {
      var n = d20();
      clearTimeout(timer);
      b.classList.remove("spin", "lit", "demon");
      void b.offsetWidth;
      b.classList.add("spin");
      out.textContent = "";
      Sound.play("dice");
      setTimeout(function () {
        Sound.play("land");
        out.textContent = n === 1 ? "1 · DRAGON" : n === 20 ? "20 · DEMON" : String(n);
        if (n === 1) { b.classList.add("lit"); FX.run("dragon"); }
        if (n === 20) { b.classList.add("demon"); FX.run("demon"); }
        timer = setTimeout(function () { out.textContent = ""; b.classList.remove("lit", "demon"); }, 4000);
      }, 700);
    });
    // Right click the plugin's d20 and the Book opens.
    b.addEventListener("contextmenu", function (e) { e.preventDefault(); $("#book").scrollIntoView({ behavior: reduced ? "auto" : "smooth" }); });
    // The player's line in the hero says what it does.
    var line = $("#player-roll");
    if (line) line.addEventListener("click", function () { b.click(); });
  }

  // Title cards: decrypting out of noise ----------------------------------------------

  var NOISE = "░▒▓█/\\|<>*+#%&@$~=-_";
  function prepareDecrypt(el) {
    var text = el.dataset.text || el.textContent;
    el.setAttribute("aria-label", text);
    el.innerHTML = '<span class="noise" aria-hidden="true"></span><span class="final" aria-hidden="true"></span>';
    el.lastChild.textContent = text;
    el.firstChild.textContent = scramble(text, 0);
  }
  function scramble(text, revealed) {
    var out = "";
    for (var i = 0; i < text.length; i++) out += i < revealed || text[i] === " " ? text[i] : NOISE[Math.floor(Math.random() * NOISE.length)];
    return out;
  }
  function decrypt(el) {
    if (el.dataset.done) return;
    el.dataset.done = "1";
    var text = el.getAttribute("aria-label") || "", noise = el.firstChild, revealed = 0, still = 0;
    if (reduced) { el.classList.add("settled", "cooled"); return; }
    el.classList.add("running");
    var timer = setInterval(function () {
      // About every other tick a letter settles, and never fewer than one in three.
      if (Math.random() < 0.55 || ++still >= 3) { revealed += 1; still = 0; }
      noise.textContent = scramble(text, revealed);
      if (revealed >= text.length) {
        clearInterval(timer);
        el.classList.add("settled");
        setTimeout(function () { el.classList.add("cooled"); }, 2400);
      }
    }, 38);
  }
  function titleCards() {
    var titles = $$(".decrypt");
    titles.forEach(prepareDecrypt);
    var reveal = function (head) {
      head.classList.add("revealed");
      var t = $(".decrypt", head);
      if (t) decrypt(t);
    };
    var heads = $$(".card-head, .hero-copy");
    if (!("IntersectionObserver" in window)) { heads.forEach(reveal); return; }
    // A title is readable until it's about to come into view; then it decrypts, the way a
    // scene's name does when the hero walks in.
    var io = new IntersectionObserver(function (entries) {
      entries.forEach(function (e) {
        if (e.isIntersecting) { reveal(e.target); io.unobserve(e.target); }
      });
    }, { rootMargin: "0px 0px 12% 0px" });
    heads.forEach(function (h) { io.observe(h); });
  }

  // The GM writes: words stream in ----------------------------------------------------

  // Quick enough that the first paragraph is whole within about a second and a half: it's
  // the one every visitor reads.
  function streams() {
    $$(".stream").forEach(function (p) {
      if (reduced) return;
      var words = p.textContent.split(/(\s+)/);
      p.innerHTML = words.map(function (w) { return /^\s+$/.test(w) ? w : '<span class="w">' + esc(w) + "</span>"; }).join("");
      var spans = $$(".w", p), started = false;
      function go() {
        if (started) return;
        started = true;
        var i = 0;
        (function next() {
          if (i >= spans.length) return;
          spans[i++].classList.add("on");
          setTimeout(next, 12 + Math.random() * 18);
        })();
      }
      if ("IntersectionObserver" in window) {
        var io = new IntersectionObserver(function (es) { if (es[0].isIntersecting) { setTimeout(go, 350); io.disconnect(); } });
        io.observe(p);
      } else go();
    });
  }

  // Faces in text, from the engine's own drawings ------------------------------------

  var INK = { ".": "dot", e: "e", b: "b", m: "m", w: "w", a: "a", h: "h", g: "g", o: "o" };
  function tintOf(mood) { return mood === "dead" || mood === "dying" || mood === "hurt" ? "grave" : mood === "triumph" ? "bright" : "normal"; }
  function drawFace(pre, hero, mood, flicker) {
    var set = ART.heroes[hero];
    if (!set) return;
    var art = set[mood] || set.calm, lines = art[0], ink = art[1], html = "";
    for (var i = 0; i < lines.length; i++) {
      var line = lines[i], marks = ink[i] || "", run = "", kind = null;
      for (var j = 0; j < line.length; j++) {
        var ch = line[j], k = ch === " " ? " " : (INK[marks[j]] ? marks[j] : ".");
        if (k !== kind) { if (run) html += wrapInk(kind, run); run = ""; kind = k; }
        run += ch;
      }
      if (run) html += wrapInk(kind, run);
      html += "\n";
    }
    pre.innerHTML = html;
    pre.dataset.hero = hero;
    pre.dataset.mood = mood;
    pre.dataset.tint = tintOf(mood);
    pre.dataset.wounds = mood === "hurt" ? "2" : "0";
    if (flicker && !reduced) {
      pre.classList.remove("flicker");
      void pre.offsetWidth;
      pre.classList.add("flicker");
    }
  }
  function wrapInk(kind, run) { return kind === " " ? run : '<span class="i-' + INK[kind] + '">' + esc(run) + "</span>"; }

  // Now and then the eyes close for a moment, as long as they are open.
  function blinker(pre) {
    (function schedule() {
      setTimeout(function () {
        var mood = pre.dataset.mood;
        if (mood !== "dead" && mood !== "dying" && !reduced) {
          var eyes = $$(".i-e", pre), was = eyes.map(function (e) { return e.textContent; });
          eyes.forEach(function (e) { e.textContent = e.textContent.replace(/[^ ]/g, "─"); });
          setTimeout(function () { eyes.forEach(function (e, i) { if (e.isConnected) e.textContent = was[i]; }); }, 150);
        }
        schedule();
      }, 3200 + Math.random() * 4000);
    })();
  }
  function faces() {
    $$("pre.portrait[data-hero]").forEach(function (pre) {
      drawFace(pre, pre.dataset.hero, pre.dataset.mood || "calm");
      blinker(pre);
    });
    $$(".bar-blocks").forEach(function (m) { meter(m, +m.dataset.value, +m.dataset.max); });

    var lab = $("#lab-face");
    if (!lab) return;
    function press(group, attr, value) {
      $$("#" + group + " .chip").forEach(function (c) { c.setAttribute("aria-pressed", String(c.dataset[attr] === value)); });
    }
    $("#lab-heroes").addEventListener("click", function (e) {
      var c = e.target.closest(".chip");
      if (!c) return;
      press("lab-heroes", "hero", c.dataset.hero);
      drawFace(lab, c.dataset.hero, lab.dataset.mood, true);
    });
    $("#lab-moods").addEventListener("click", function (e) {
      var c = e.target.closest(".chip");
      if (!c) return;
      press("lab-moods", "mood", c.dataset.mood);
      drawFace(lab, lab.dataset.hero, c.dataset.mood, true);
      if (c.dataset.mood === "dead") Sound.play("bell");
      else if (c.dataset.mood === "dying") Sound.play("heart");
      else if (c.dataset.mood === "triumph") Sound.play("chime");
    });
  }
  function meter(el, value, max) {
    var cells = 14, filled = Math.max(0, Math.min(cells, Math.round(cells * value / Math.max(1, max))));
    el.classList.toggle("low", value * 4 <= max);
    el.innerHTML = "█".repeat(filled) + '<span class="empty">' + "░".repeat(cells - filled) + "</span>";
  }

  // The dice moment --------------------------------------------------------------------

  function d20Art(n) {
    var s = String(n), label = s.length === 1 ? "  " + s + "  " : " " + s + "  ";
    return "     .-^-.\n" +
      "  .-' / \\ '-.\n" +
      " /   /   \\   \\\n" +
      "|   /" + label + "\\   |\n" +
      "|  /_______\\  |\n" +
      " \\  \\     /  /\n" +
      "  '-.\\   /.-'\n" +
      "     '-.-'";
  }

  function burstParticles(host, color, count, spread, fall) {
    if (reduced || !host) return;
    for (var i = 0; i < count; i++) {
      var s = document.createElement("i");
      var a = Math.random() * Math.PI * 2, r = spread * (0.35 + Math.random() * 0.75);
      s.style.setProperty("--x", Math.cos(a) * r + "px");
      s.style.setProperty("--y", Math.sin(a) * r + (fall ? spread * 0.6 : 0) + "px");
      s.style.setProperty("--t", 0.7 + Math.random() * 0.9 + "s");
      s.style.setProperty("--c", color);
      host.appendChild(s);
      setTimeout(function (el) { el.remove(); }, 1800, s);
    }
  }

  // Tumble, slow, land: the Book's rhythm (14 ticks, each longer than the last).
  function tumble(opts) {
    var row = opts.row, finals = opts.finals, ticks = 0;
    row.classList.add("tumbling");
    return new Promise(function (done) {
      function tick() {
        ticks += 1;
        if (ticks >= 14 || reduced) {
          row.classList.remove("tumbling");
          opts.draw(finals, true);
          done();
          return;
        }
        opts.draw(finals.map(function () { return d20(); }), false);
        setTimeout(tick, 45 + ticks * ticks * 1.6);
      }
      tick();
    });
  }

  function roller() {
    var root = $("#roller");
    if (!root) return;
    var state = { skill: "Swords", target: 14, boons: 0, banes: 0, conditions: [], busy: false };
    var card = $("#dice-card"), row = $("#dice-row"), label = $("#dice-label"), need = $("#dice-need");
    var verdict = $("#verdict"), ring = $("#ring"), sparks = $("#sparks"), log = $("#roll-log");
    var push = $("#push"), pushChips = $("#push-chips"), rest = $("#rest-btn");
    var CONDITIONS = ["exhausted", "sickly", "dazed", "angry", "scared", "disheartened"];
    var heroFace = $(".roll-hero pre.portrait", root), conds = $("#sheet-conds");

    function draw(faces, landed, result) {
      row.innerHTML = faces.map(function (f) {
        var cls = "d20";
        if (landed && faces.length > 1) cls += f === result ? " counts" : " dim";
        else if (landed) cls += " counts";
        return '<pre class="' + cls + '">' + esc(d20Art(f)) + "</pre>";
      }).join("");
    }
    function idle() {
      label.textContent = state.skill.toUpperCase();
      need.textContent = "needs " + state.target + " or less";
      draw([20].concat(Math.abs(state.boons - state.banes) ? [20] : []), false);
    }
    function mood() { return state.conditions.length ? state.conditions[state.conditions.length - 1] : "calm"; }
    function faceTo(m) {
      if (heroFace) drawFace(heroFace, "ragna", m, true);
      // The sheet lists what she's carrying, the way the Table does.
      if (conds) {
        conds.textContent = state.conditions.length ? state.conditions.join(", ") : "no conditions";
        conds.classList.toggle("held", state.conditions.length > 0);
      }
    }

    root.addEventListener("click", function (e) {
      var chip = e.target.closest(".skills .chip");
      if (chip && !state.busy) {
        $$(".skills .chip", root).forEach(function (c) { c.setAttribute("aria-pressed", String(c === chip)); });
        state.skill = chip.dataset.skill;
        state.target = +chip.dataset.target;
        push.hidden = true;
        idle();
      }
      var step = e.target.closest(".step");
      if (step && !state.busy) {
        var k = step.dataset.step;
        state[k] = Math.max(0, Math.min(3, state[k] + +step.dataset.by));
        $("#" + k).textContent = state[k];
        idle();
      }
    });

    function roll(pushed) {
      if (state.busy) return;
      state.busy = true;
      push.hidden = true;
      var extra = Math.abs(state.boons - state.banes);
      var faces = [];
      for (var i = 0; i < 1 + extra; i++) faces.push(d20());
      var result = state.boons > state.banes ? Math.min.apply(null, faces) : state.banes > state.boons ? Math.max.apply(null, faces) : faces[0];
      var dragon = result === 1, demon = result === 20;
      var success = dragon || (!demon && result <= state.target);
      card.className = "dice-card";
      verdict.className = "verdict";
      verdict.textContent = " ";
      label.textContent = (pushed ? "PUSHED · " : "") + state.skill.toUpperCase();
      card.style.removeProperty("--verdict");
      Sound.play("dice");
      tumble({ row: row, finals: faces, draw: function (f, landed) { draw(f, landed, result); } }).then(function () {
        var color = dragon ? "var(--gold)" : !success ? "var(--urgent)" : "var(--accent)";
        card.style.setProperty("--verdict", color);
        card.classList.add(dragon ? "dragon" : demon ? "demon" : success ? "ok" : "fail", "pop");
        verdict.textContent = dragon ? "DRAGON" : demon ? "DEMON" : success ? "SUCCESS" : "FAILURE";
        void verdict.offsetWidth;
        verdict.classList.add("on");
        ring.classList.remove("go"); void ring.offsetWidth; ring.classList.add("go");
        Sound.play("land");
        if (dragon) {
          Sound.play("chime", 0.05);
          burstParticles(sparks, "var(--gold)", 60, 170, false);
          faceTo("triumph");
          setTimeout(function () { faceTo(mood()); }, 4200);
        }
        if (demon) {
          Sound.play("growl", 0.05);
          card.classList.add("shake");
          burstParticles(sparks, "var(--urgent)", 36, 130, true);
          if (heroFace) { heroFace.classList.remove("flicker"); void heroFace.offsetWidth; heroFace.classList.add("flicker"); }
        }
        log.textContent = state.skill + ": " + faces.join(" and ") + (faces.length > 1 ? " (" + result + " counts)" : "") +
          " vs " + state.target + ", " + (dragon ? "a Dragon" : demon ? "a Demon" : success ? "success" : "failure") + (pushed ? ", pushed" : "");
        // A failure that isn't a Demon can be pushed, once, for a condition not already held.
        var free = CONDITIONS.filter(function (c) { return state.conditions.indexOf(c) === -1; });
        if (!success && !demon && !pushed && free.length) {
          pushChips.innerHTML = free.map(function (c) { return '<button type="button" class="chip" data-cond="' + c + '">' + c + "</button>"; }).join("");
          push.hidden = false;
        }
        state.busy = false;
      });
    }
    $("#roll-btn").addEventListener("click", function () { roll(false); });
    pushChips.addEventListener("click", function (e) {
      var c = e.target.closest(".chip");
      if (!c || state.busy) return;
      state.conditions.push(c.dataset.cond);
      faceTo(mood());
      rest.hidden = false;
      roll(true);
    });
    rest.addEventListener("click", function () {
      state.conditions.pop();
      faceTo(mood());
      Sound.play("torch");
      rest.hidden = !state.conditions.length;
      log.textContent = "Stretch rest. " + (state.conditions.length ? "Still " + state.conditions.join(", ") + "." : "No conditions left.");
    });
    idle();
  }

  // The desktop joins in ---------------------------------------------------------------

  var OMENS = [
    "The drums below have stopped.",
    "Somewhere under your feet, a chant rises and falls.",
    "Every candle in the room leans the same way.",
    "The water in your flask has gone warm.",
    "A crow lands on the sill and will not look away."
  ];
  var FX = (function () {
    var html = document.documentElement, mock = null, dying = 0, beats = null, timers = {};
    function targets() { return [html, mock].filter(Boolean); }
    function flash(cls, ms) {
      targets().forEach(function (t) { t.classList.remove(cls); void t.offsetWidth; t.classList.add(cls); });
      clearTimeout(timers[cls]);
      timers[cls] = setTimeout(function () { targets().forEach(function (t) { t.classList.remove(cls); }); }, ms);
    }
    function heartbeat() {
      clearInterval(beats);
      var count = 0;
      Sound.play("heart");
      beats = setInterval(function () {
        if (!dying || ++count > 6) { clearInterval(beats); return; }
        Sound.play("heart");
      }, 1100);
    }
    function setDying(level) {
      dying = level;
      targets().forEach(function (t) {
        t.classList.toggle("dying", level > 0);
        t.classList.toggle("fx-dark-red", level > 0);
        t.style.setProperty("--rim", 40 + level * 45 + "px");
        t.style.setProperty("--rim-spread", level * 12 + "px");
      });
    }
    var run = {
      dragon: function () { flash("fx-gold", 1300); flash("flood", 1900); Sound.play("chime"); },
      demon: function () { flash("fx-red", 1400); flash("fx-drain", 1200); flash("torn", 1300); Sound.play("growl"); },
      hit: function () { flash("jolt", 340); Sound.play("hit"); },
      dying: function () { setDying(Math.min(3, dying + 1)); heartbeat(); },
      death: function () {
        setDying(0);
        clearInterval(beats);
        flash("fx-dead", 6500);
        Sound.play("bell");
        toast("Ragna is dead", "Fell at the Fiendish Altar, to a demon cultist.", "red");
      },
      omen: function () {
        flash("rippling", 1700);
        Sound.play("omen");
        toast("An omen", OMENS[Math.floor(Math.random() * OMENS.length)]);
      },
      candle: function () {
        var on = !html.classList.contains("candle");
        targets().forEach(function (t) { t.classList.toggle("candle", on); });
        if (on) Sound.play("torch");
        return on;
      },
      drum: function () { flash("jolt", 340); Sound.play("drum"); },
      restore: function (quiet) {
        setDying(0);
        clearInterval(beats);
        ["fx-gold", "flood", "fx-red", "fx-drain", "torn", "jolt", "fx-dead", "rippling", "candle"].forEach(function (c) {
          targets().forEach(function (t) { t.classList.remove(c); });
        });
        $$(".fx-btn.on").forEach(function (b) { b.classList.remove("on"); });
        if (!quiet) toast("Restored", "Your border colours, your screen shader and your screen temperature are back as they were.", "gold");
      }
    };
    return {
      attach: function (el) { mock = el; },
      run: function (name, arg) { return run[name] ? run[name](arg) : undefined; }
    };
  })();

  function toast(title, text, tone) {
    var host = $("#notify");
    if (!host) return;
    var t = document.createElement("div");
    t.className = "toast" + (tone ? " " + tone : "");
    t.innerHTML = "<b>" + esc(title) + "</b>" + esc(text);
    host.appendChild(t);
    setTimeout(function () { t.classList.add("out"); setTimeout(function () { t.remove(); }, 450); }, 5200);
  }

  function desktop() {
    var mock = $("#mock");
    if (!mock) return;
    FX.attach(mock);
    $$(".fx-btn").forEach(function (b) {
      b.addEventListener("click", function () {
        var result = FX.run(b.dataset.fx);
        if (b.dataset.fx === "candle") b.classList.toggle("on", !!result);
      });
    });
  }

  // Screens, looked at closer ---------------------------------------------------------

  function lightbox() {
    var dialog = $("#lightbox");
    if (!dialog || typeof dialog.showModal !== "function") return;
    var img = $("#lb-img"), cap = $("#lb-cap"), group = [], at = 0;
    function show(i) {
      at = (i + group.length) % group.length;
      var fig = group[at], src = $("img", fig);
      img.src = src.currentSrc || src.src;
      img.alt = src.alt;
      cap.textContent = fig.dataset.caption || src.alt;
    }
    $$("figure.shot").forEach(function (fig) {
      fig.tabIndex = 0;
      fig.setAttribute("role", "button");
      fig.setAttribute("aria-label", "Look closer: " + ($("img", fig) || {}).alt);
      function open() {
        var box = fig.closest(".gallery, .shelf-shots");
        group = box ? $$("figure.shot", box) : [fig];
        show(group.indexOf(fig));
        dialog.showModal();
      }
      fig.addEventListener("click", open);
      fig.addEventListener("keydown", function (e) { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); open(); } });
    });
    $("#lb-prev").addEventListener("click", function () { show(at - 1); });
    $("#lb-next").addEventListener("click", function () { show(at + 1); });
    dialog.addEventListener("keydown", function (e) {
      if (e.key === "ArrowLeft") show(at - 1);
      if (e.key === "ArrowRight") show(at + 1);
    });
    dialog.addEventListener("click", function (e) { if (e.target === dialog) dialog.close(); });
  }

  // The trailer: a tab for each cut that's there; a placeholder only if none is -------------

  function videos() {
    var tabs = $$(".tabs [role=tab]"), tablist = $(".tabs");
    function select(tab) {
      tabs.forEach(function (t) {
        var on = t === tab, panel = $("#" + t.getAttribute("aria-controls"));
        t.setAttribute("aria-selected", String(on));
        panel.hidden = !on;
        var v = $("video", panel);
        if (!on && v && !v.paused) v.pause();
      });
    }
    function placeholder(box) {
      if ($(".placeholder", box)) return;
      var ph = document.createElement("div");
      ph.className = "placeholder";
      ph.innerHTML = '<div><pre class="ph-die" aria-hidden="true">' + esc(d20Art(20)) + '</pre>' +
        '<div class="rule revealed" aria-hidden="true"><span></span><i>◆</i><span></span></div>' +
        '<p class="ph-title">The trailer rises here</p>' +
        '<p class="ph-file">' + esc(box.dataset.file) + "</p></div>";
      box.appendChild(ph);
      $("video", box).hidden = true;
    }
    // A cut whose file isn't in media/ (or won't play here) loses its tab. The tabs step
    // aside when one cut is left, and the last one shows where its file goes.
    function missing(box) {
      if (box.dataset.missing) return;
      box.dataset.missing = "1";
      var tab = tabs.filter(function (t) { return t.getAttribute("aria-controls") === box.id; })[0];
      var left = tabs.filter(function (t) { return !$("#" + t.getAttribute("aria-controls")).dataset.missing; });
      if (!left.length) {
        // None is there: the first cut's panel says where its file goes.
        var first = $("#" + tabs[0].getAttribute("aria-controls"));
        select(tabs[0]);
        placeholder(first);
        if (tablist) tablist.hidden = true;
        return;
      }
      if (tab) tab.hidden = true;
      if (tab && tab.getAttribute("aria-selected") === "true") select(left[0]);
      if (tablist) tablist.hidden = left.length < 2;
    }
    // Only the cuts that exist are in the page, so a missing one never costs a request; one cut needs no tabs.
    if (tablist) tablist.hidden = tabs.length < 2;
    $$(".video").forEach(function (box) {
      var video = $("video", box), source = $("source", box);
      if (source) source.addEventListener("error", function () { missing(box); });
      video.addEventListener("error", function () { missing(box); });
      if (video.canPlayType && !video.canPlayType("video/mp4")) missing(box);
    });
    tabs.forEach(function (tab) { tab.addEventListener("click", function () { select(tab); }); });
  }

  // Terminals that type themselves -----------------------------------------------------

  function terminals() {
    $$("[data-replay] .term-body").forEach(function (body) {
      var lines = Array.prototype.slice.call(body.children);
      var cwd = "";
      lines.forEach(function (line) {
        if (line.hasAttribute("data-cmd")) {
          if (line.dataset.cwd) cwd = line.dataset.cwd;
          line.dataset.text = line.textContent;
          line.dataset.prompt = "";
          // What's still to be typed sits there in transparent ink, holding the line's room.
          line.innerHTML = '<span class="cwd">' + esc(cwd || "~") + '</span> <span class="ps">❯</span> <span class="typed"></span><span class="rest"></span>';
          $(".ps", line).style.color = "var(--green)";
          $(".rest", line).textContent = line.dataset.text;
        }
      });
      var prompt = document.createElement("p");
      prompt.innerHTML = '<span class="cwd">' + esc(cwd || "~") + '</span> <span style="color:var(--green)">❯</span> ';
      body.appendChild(prompt);
      function finish(line) { $(".typed", line).textContent = line.dataset.text; $(".rest", line).textContent = ""; }
      // Complete at rest; typed again from the top as it comes into view.
      lines.forEach(function (l) { if (l.dataset.text) finish(l); });
      if (reduced || !("IntersectionObserver" in window)) return;
      var io = new IntersectionObserver(function (es) {
        if (!es[0].isIntersecting) return;
        io.disconnect();
        lines.concat(prompt).forEach(function (l) {
          l.classList.add("pending");
          if (l.dataset.text) { $(".typed", l).textContent = ""; $(".rest", l).textContent = l.dataset.text; }
        });
        play();
      }, { rootMargin: "0px 0px 10% 0px" });
      io.observe(body);
      async function play() {
        var caret = document.createElement("span");
        caret.className = "caret";
        for (var i = 0; i < lines.length; i++) {
          var line = lines[i];
          line.classList.remove("pending");
          if (line.dataset.text) {
            var typed = $(".typed", line), rest = $(".rest", line), text = line.dataset.text;
            rest.before(caret);
            await wait(260);
            for (var c = 0; c <= text.length; c += 2) {
              typed.textContent = text.slice(0, c);
              rest.textContent = text.slice(c);
              await wait(14);
            }
            finish(line);
            await wait(320);
            caret.remove();
          } else {
            await wait(line.tagName === "PRE" ? 120 : 70);
          }
        }
        prompt.classList.remove("pending");
        prompt.appendChild(caret);
      }
    });
  }

  function copies() {
    $$(".copy[data-copy]").forEach(function (b) {
      b.addEventListener("click", function () {
        var text = ($("#" + b.dataset.copy) || {}).textContent || "";
        var done = function () { b.textContent = "copied"; setTimeout(function () { b.textContent = "copy"; }, 1600); };
        // Where the clipboard is refused, the commands are selected for a Ctrl+C instead.
        var select = function () {
          var range = document.createRange(), sel = window.getSelection();
          range.selectNodeContents($("#" + b.dataset.copy));
          sel.removeAllRanges(); sel.addRange(range);
          b.textContent = "selected";
          setTimeout(function () { b.textContent = "copy"; }, 1600);
        };
        if (navigator.clipboard && navigator.clipboard.writeText) navigator.clipboard.writeText(text).then(done, select);
        else select();
      });
    });
  }

  // Some doors only open for those who remember the old codes -------------------------

  function konami() {
    var CODE = ["arrowup", "arrowup", "arrowdown", "arrowdown", "arrowleft", "arrowright", "arrowleft", "arrowright", "b", "a"];
    var at = 0;
    document.addEventListener("keydown", function (e) {
      var k = (e.key || "").toLowerCase();
      if (k === CODE[at]) {
        at += 1;
        if (at === CODE.length) { at = 0; openSecret(); }
      } else {
        at = k === CODE[0] ? 1 : 0;
      }
    });
    // On a phone: swipe up, up, down, down, left, right, left, right, then tap twice.
    var start = null, swipes = [], taps = 0, SWIPES = "uuddlrlr";
    document.addEventListener("touchstart", function (e) { var t = e.changedTouches[0]; start = { x: t.clientX, y: t.clientY, at: Date.now() }; }, { passive: true });
    document.addEventListener("touchend", function (e) {
      if (!start) return;
      var t = e.changedTouches[0], dx = t.clientX - start.x, dy = t.clientY - start.y;
      var far = Math.max(Math.abs(dx), Math.abs(dy));
      if (far < 12 && Date.now() - start.at < 300) {
        if (swipes.join("") === SWIPES) { taps += 1; if (taps === 2) { swipes = []; taps = 0; openSecret(); } }
        return;
      }
      if (far < 40) return;
      var dir = Math.abs(dx) > Math.abs(dy) ? (dx > 0 ? "r" : "l") : (dy > 0 ? "d" : "u");
      swipes.push(dir);
      taps = 0;
      if (SWIPES.indexOf(swipes.join("")) !== 0) swipes = dir === "u" ? ["u"] : [];
      if (swipes.length > SWIPES.length) swipes = [];
    }, { passive: true });
  }

  var loading = false;
  function openSecret() {
    if (document.documentElement.classList.contains("secret-open") || loading) return;
    var start = function () { window.OMA_SECRET.open({ Sound: Sound, FX: FX, drawFace: drawFace, d20Art: d20Art, tumble: tumble, burst: burstParticles, toast: toast, store: store, reduced: reduced }); };
    // The bar's d20 spins and lands on a 1 before the door opens.
    var b = $("#bar-d20"), out = $("#bar-roll");
    b.classList.remove("spin", "lit", "demon"); void b.offsetWidth; b.classList.add("spin");
    Sound.play("dice");
    setTimeout(function () {
      Sound.play("land");
      out.textContent = "1 · DRAGON";
      b.classList.add("lit");
      FX.run("dragon");
    }, 700);
    if (window.OMA_SECRET) { setTimeout(start, 1500); return; }
    loading = true;
    var s = document.createElement("script");
    s.src = "secret.js";
    s.onload = function () { loading = false; setTimeout(start, 900); };
    s.onerror = function () { loading = false; toast("The door is stuck", "secret.js didn't load.", "red"); };
    document.body.appendChild(s);
  }

  // ---------------------------------------------------------------------------------

  function init() {
    applyTheme(document.documentElement.dataset.omaTheme || "tokyo-night", false);
    walker();
    clock();
    workspaces();
    soundButton();
    barDie();
    titleCards();
    streams();
    faces();
    roller();
    desktop();
    lightbox();
    videos();
    terminals();
    copies();
    konami();
    if (window.console && console.log) {
      console.log("%c◆ oma-solorpg", "color:#e0af68;font:600 14px monospace");
      console.log("%cThe tower rises for those who remember the old code.", "color:#7a82a8;font:italic 12px serif");
    }
  }
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
