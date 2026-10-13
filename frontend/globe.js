/* The login screen's globe.
 *
 * A dotted Earth turning slowly behind the sign-in form, with field reports
 * arcing in from around it to one point — the console they are all sent to.
 * It is the only ambient motion in the app, and it lives only here: the
 * screen where nobody is working yet and there is room for it.
 *
 * Built to cost nothing once it is out of sight:
 *   - drawn on one canvas with 2D calls, no libraries, nothing fetched;
 *   - stops when the login screen is hidden (i.e. the moment someone logs
 *     in) and when the browser tab is in the background, and starts again
 *     when the screen comes back (log out, session expiry);
 *   - draws a single still frame, arcs and all, when the system asks for
 *     reduced motion;
 *   - takes every colour from the live palette tokens, and redraws when the
 *     palette, light/dark or brand accent changes.
 *
 * THE LAND
 *
 * The dots are a 16,000-point Fibonacci sphere, an even scatter over the
 * globe; MASK below holds one bit per point saying whether it falls on land
 * (about 4,600 do). It was computed once from Natural Earth's 1:110m land
 * polygons (public domain, via the world-atlas package) and is 2.6 KB here,
 * rather than shipping a map file to draw a backdrop.
 */
(function () {
  "use strict";
  var canvas = document.getElementById("auth-globe");
  var screenEl = document.getElementById("auth-screen");
  if (!canvas || !screenEl || !canvas.getContext) return;
  var ctx = canvas.getContext("2d");
  if (!ctx) return;

  var MASK = "AAAAAAAAABAAQkBIAAhJIQshJISEhIAUEBJCgkLAAJk6IQNgYAAMhJEDMjIADsTYgZk5Mkdi7sjMuplpcfEsbu3MprzXNv/6Stvf+zt/f+3t/u2Vv7/+9t732tv5/ztvf+ft/f+dt/v21v7+2lt5eztv9++tvN21t/L3Vsbu31t5Oysn5e+snJ2Xk3J3VmbO3Um5OSMr5+ak7JyR03JzQn7OzUmZOSMv5+aE7Jy70zNzQn7OzInZOTG3Z+bk/Jybk3NzRm7Pzen5OTU35+bk3Jyb03NzSm7Ozem5OTW35+bU3Jybk3Nzak7Pzek5OTUn5+T0nJyb03Nzam7Pzak5OTW35+bUnJybU3Nyam7Ozam5OTWn4+bUnJybUXNzakbGzak5OTGj5ubUnIybUXNyakbNzeg5OTOj5uTEjIqTkXN6akbFyYg5NSOj5+TEjIqREXNqTk7FyYkZNScmZ9SEnIqTE3NqRkzMyYk5FSMmZtSEmIiRE3NqRkzOqQk5FSMmZtSUmJyTE3JqRk7MqAk5ESOmZtSEjJ6RUzJiRkzNiAkZPSOmZvSEmJoREzJ6RkzN6AkZNSOmZNSEmJpREzJqRkzJ6Ak5NSOmZNSEmJLRUzJqTkzJqAkxJaemZNSEmJJRU3JqTkzJqSkxJaem5NSUmJJTUnJqSk3JKSkxJaem5JSUmJJTUGJKSknJKSkxJaek5NSUkpJTUGJKSknJKCklJaekxFSckpJTUGpKSknJKCglJaekxJSUkpJTUEpKSkmJKCklBaek1BSckgJTUEoKSkmpKCklBaeklBSckgJTUkoKSkmpKCklBaamlBSUkkJTUkoKSEmpoSklBaaklBSQmkJBUkoKTEmhqSA1BYaElFSQkkJBQEoqDAkpKSA1hYaklBSQkkJBQGoqDAmpKSAlhYaA1BQQkkJBQGoKCgGpKSAkhYaA1BQQglJBQEoKCwGpISAEhYKA1BQUglJCQGgKCQGpKSAUhYCA0BQWglJCQCgKCQGpKSAEpYCAUBQWAlJCQCgKCQEhICgEpYCAUBQSAlJQQAgKCQEhICQEpICAUBQSAlJAQQgKCQUhISQEpICCUFQSAkJCQQhoCQUhoCQEhISCUFASCkJCQShICQUhqCwEpISCUFASCkJAUQgICQUhoCwUpISCUFASCkJAUQgICQUhoCQUhICCEFASCkJAUSgISQUBoCQUlYCCEFASigJAQSgoQAUBoCQVFYCCAFAQCgJAQSgqQAUBoCAVFICCQFQACgJAQSgqAAWBqAAVBICCUFQACgJAQSgqAAWBqAAVBICiUFQACgJRASgoAAWBqAAVBKACUFQACgJRASoqAAWgqAAVBKICUFAACgJRESooAAWgqAAVFKICUFAACkBRASooBAWgoAgVFKIiUFQECkhRESooBAWkoAgUEIICUFQMCkhBESooBgXkoAgUEIICUFQMCkhBESogBgWkoAgUEIICUFAMCkhBESogBkWkoAgUEIICUECMCkhBESogBAWgoBgVkIIiUECICkhBESggBAWgoBAUkIICUEAMCkBBASggBAWggBAUkKICUEAICkBBASggBAWggBAUgIICUEAICkBBASggBQWggBAUgIIiUEAICkABISgCBQWggBAUgYICUAQKCkABISgKBUWgiBAUgIICUAQKCkARISgABUWgiBQUgCICUBQKCkARISgCBUWgKBQUgCIDUAQKikBRKSgCRUSgKBQUgCICUASKiEBRCCgCRQSgKBQQgaICUASKiEBRKCgCRQSgCBQRgaIQUASKiEBRKCICRUSgCBQRgaIQVASKiEARKCICRQGoCBQRgaJQVASKiFARKCICRQGoCBQRgSJQRASKglARKCICRaGoCBQBoSJQRASKglARKAICRaCICBQBoSJQBASKgBARKAJCRaAICBQBoSJQBASKgBERKAJCRaAICBQBISJQBASKQBERKAJCRaAICBQBIyJQBASKQBEQKAJCRKAICBQBIyBQBISIQBEQKAJGRKAICBQBIiBQBISIQBEQKAJGQKAICBABIiBQAISAQAEQIABEQKAACBGBIiBAAIiAQAEQIAAEQIAACAGBAiAAAAiAAAEQAAAEQIAAEAAAAiAAAAiAAAEQAAAEQIAAEAAAAiAAAAiEAAEgAAAEQgAAEAAAAgAAAAgEAAAgAAAEAAAAEAAAAEAAAAgAAAAgAAAEQAAAEAgAAEAAAACAAAAgEAAAgAAAEAAAAEAgAACAAAAgAAAAgEAAAAAAAEAAAAAAgQAgAAAAgAAAAAAAAEAAAAAAgQAAAAAAgAAAAAAAAEAAAAAAAQAAAAAAgAAAAAACAAAAAAAAAQAAAAAAgAEAAAACAAAAAAAAAQAAAAQAAAAAEAACAAAAAAAAAQAAAAQAAAAAAAAAAAAAAAAAAQAAAAQAAAAAAAACAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAACAAAAAAACAAACSkRICQgBISUgpISUjJASUFJKSkZpKSkdJaWn9LSWjtPSWlpOS29paT0/p+f1/Jyf1/Nzfl7Pz/v5Pb/v9/f9vN6f3/N7fn/v7//9/f////8=";
  var N = 16000;
  var GOLDEN = Math.PI * (3 - Math.sqrt(5));

  // Land points as unit vectors: y is north, z faces the viewer at lon 0.
  var land = (function () {
    var bin = atob(MASK), out = [];
    for (var i = 0; i < N; i++) {
      if (!(bin.charCodeAt(i >> 3) & (1 << (i & 7)))) continue;
      var y = 1 - (i + 0.5) / N * 2, r = Math.sqrt(1 - y * y), lon = i * GOLDEN;
      out.push([r * Math.sin(lon), y, r * Math.cos(lon)]);
    }
    return out;
  })();
  var LAND = land.length;
  var projX = new Float32Array(LAND), projY = new Float32Array(LAND), projZ = new Float32Array(LAND);

  var reduceQuery = window.matchMedia ? window.matchMedia("(prefers-reduced-motion: reduce)") : null;
  var TILT = 0.38;                       // north pole leans toward the viewer
  var SPIN = (2 * Math.PI) / 140;        // one turn every 140 s
  var spin = -0.35;                      // starts with Europe and Africa facing
  var W = 0, H = 0, DPR = 1, cx = 0, cy = 0, R = 0, fade = 1;
  var colors = {};
  var arcs = [], pulses = [], hub = -1, nextSpawn = 0, hubUntil = 0;
  var raf = 0, last = 0, running = false;

  function token(name, fallback) {
    var v = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return v || fallback;
  }
  function readColors() {
    colors = {
      accent: token("--accent", "#39ff88"),
      accentRgb: token("--accent-rgb", "57,255,136"),
      dots: token("--muted", "#5f9973"),
      grid: token("--border-strong", "#357a4f"),
      disc: token("--panel", "#081a10"),
      light: document.documentElement.getAttribute("data-theme") === "light",
    };
  }

  function layout() {
    var rect = canvas.getBoundingClientRect();
    W = Math.max(1, rect.width); H = Math.max(1, rect.height);
    DPR = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(W * DPR); canvas.height = Math.round(H * DPR);
    var box = screenEl.querySelector(".auth-box");
    var right = box ? box.getBoundingClientRect().right : 0;
    if (W >= 760) {
      // Beside the form, as large as the window allows with room above and
      // below for the arcs, which rise off the surface.
      R = Math.min(H * 0.41, W * 0.31);
      cx = Math.max(W * 0.63, right + R * 0.9);
      cy = H * 0.5;
      fade = 1;
    } else {
      // Phones: up behind the top of the form, and quieter.
      R = Math.min(W * 0.66, H * 0.36);
      cx = W * 0.5; cy = H * 0.3; fade = 0.6;
    }
  }

  // Rotate a unit vector by the current spin and tilt; returns [x, y, z].
  function rotate(p, out) {
    var c = Math.cos(spin), s = Math.sin(spin);
    var x = p[0] * c + p[2] * s, z = -p[0] * s + p[2] * c, y = p[1];
    var ct = Math.cos(TILT), st = Math.sin(TILT);
    out[0] = x; out[1] = y * ct - z * st; out[2] = y * st + z * ct;
    return out;
  }
  var tmp = [0, 0, 0];

  function projectLand() {
    var c = Math.cos(spin), s = Math.sin(spin), ct = Math.cos(TILT), st = Math.sin(TILT);
    for (var i = 0; i < LAND; i++) {
      var p = land[i];
      var x = p[0] * c + p[2] * s, z = -p[0] * s + p[2] * c, y = p[1];
      projX[i] = x; projY[i] = y * ct - z * st; projZ[i] = y * st + z * ct;
    }
  }

  function slerp(a, b, t, out) {
    var d = Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2]));
    var om = Math.acos(d);
    if (om < 1e-4) { out[0] = a[0]; out[1] = a[1]; out[2] = a[2]; return out; }
    var so = Math.sin(om), k1 = Math.sin((1 - t) * om) / so, k2 = Math.sin(t * om) / so;
    out[0] = a[0] * k1 + b[0] * k2; out[1] = a[1] * k1 + b[1] * k2; out[2] = a[2] * k1 + b[2] * k2;
    return out;
  }
  function angle(a, b) {
    return Math.acos(Math.max(-1, Math.min(1, a[0] * b[0] + a[1] * b[1] + a[2] * b[2])));
  }
  function easeInOut(t) { return -(Math.cos(Math.PI * t) - 1) / 2; }

  // A random land point well on the visible face (z above a threshold).
  function pickFacing(minZ, rnd) {
    for (var tries = 0; tries < 60; tries++) {
      var i = Math.floor(rnd() * LAND);
      if (projZ[i] > minZ) return i;
    }
    return -1;
  }

  function spawn(now, rnd) {
    if (hub < 0 || projZ[hub] < 0.45 || now > hubUntil) {
      hub = pickFacing(0.82, rnd);
      hubUntil = now + 14000;
    }
    if (hub < 0) return;
    for (var tries = 0; tries < 40; tries++) {
      var o = pickFacing(0.25, rnd);
      if (o < 0) return;
      var a = angle(land[o], land[hub]);
      if (a > 0.22 && a < 1.25) {
        arcs.push({ from: o, to: hub, born: now, dur: 2200 + a * 1400,
                    lift: 0.06 + a * 0.16, arrived: false });
        return;
      }
    }
  }

  var sample = [0, 0, 0], rot = [0, 0, 0];
  // Screen position of an arc point, or null if the globe hides it.
  function arcPoint(arc, t) {
    slerp(land[arc.from], land[arc.to], t, sample);
    var h = 1 + arc.lift * Math.sin(Math.PI * t);
    rotate(sample, rot);
    var x = rot[0] * h, y = rot[1] * h, z = rot[2] * h;
    if (z < 0 && x * x + y * y < 1) return null;   // behind the globe
    return [cx + x * R, cy - y * R, z];
  }

  function drawArc(arc, head, tail, alpha) {
    if (head <= tail) return;
    var steps = 28, started = false;
    ctx.beginPath();
    for (var k = 0; k <= steps; k++) {
      var t = tail + (head - tail) * (k / steps);
      var p = arcPoint(arc, t);
      if (!p) { started = false; continue; }
      if (!started) { ctx.moveTo(p[0] * DPR, p[1] * DPR); started = true; }
      else ctx.lineTo(p[0] * DPR, p[1] * DPR);
    }
    ctx.globalAlpha = alpha * fade;
    ctx.stroke();
  }

  function draw(now) {
    ctx.setTransform(1, 0, 0, 1, 0, 0);
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    var X = cx * DPR, Y = cy * DPR, RR = R * DPR;

    // Atmosphere: a soft ring of the accent just outside the limb.
    var g = ctx.createRadialGradient(X, Y, RR * 0.9, X, Y, RR * 1.28);
    g.addColorStop(0, "rgba(" + colors.accentRgb + "," + (colors.light ? 0.10 : 0.14) * fade + ")");
    g.addColorStop(1, "rgba(" + colors.accentRgb + ",0)");
    ctx.globalAlpha = 1; ctx.fillStyle = g;
    ctx.beginPath(); ctx.arc(X, Y, RR * 1.3, 0, Math.PI * 2); ctx.fill();

    // The disc, so the far side's arcs read as behind something.
    ctx.globalAlpha = (colors.light ? 0.75 : 0.6) * fade; ctx.fillStyle = colors.disc;
    ctx.beginPath(); ctx.arc(X, Y, RR, 0, Math.PI * 2); ctx.fill();
    ctx.globalAlpha = 0.6 * fade; ctx.strokeStyle = colors.grid; ctx.lineWidth = DPR;
    ctx.stroke();

    // Graticule every 30 degrees, faint: the globe is a map, not a ball.
    ctx.lineWidth = 0.8 * DPR; ctx.strokeStyle = colors.grid; ctx.globalAlpha = 0.22 * fade;
    ctx.beginPath();
    var lat, lon, k, p, started;
    for (lat = -60; lat <= 60; lat += 30) {
      started = false;
      for (k = 0; k <= 72; k++) {
        lon = k * 5 * Math.PI / 180; var la = lat * Math.PI / 180;
        rotate([Math.cos(la) * Math.sin(lon), Math.sin(la), Math.cos(la) * Math.cos(lon)], tmp);
        if (tmp[2] < 0) { started = false; continue; }
        if (!started) { ctx.moveTo(X + tmp[0] * RR, Y - tmp[1] * RR); started = true; }
        else ctx.lineTo(X + tmp[0] * RR, Y - tmp[1] * RR);
      }
    }
    for (lon = 0; lon < 360; lon += 30) {
      started = false;
      for (k = 0; k <= 36; k++) {
        var la2 = (-90 + k * 5) * Math.PI / 180, lo = lon * Math.PI / 180;
        rotate([Math.cos(la2) * Math.sin(lo), Math.sin(la2), Math.cos(la2) * Math.cos(lo)], tmp);
        if (tmp[2] < 0) { started = false; continue; }
        if (!started) { ctx.moveTo(X + tmp[0] * RR, Y - tmp[1] * RR); started = true; }
        else ctx.lineTo(X + tmp[0] * RR, Y - tmp[1] * RR);
      }
    }
    ctx.stroke();

    // Land: one square per point, dimmer toward the limb. Bucketed by
    // brightness so the whole face is five fills, not four thousand.
    projectLand();
    var size = Math.max(1.3, R / 230) * DPR, half = size / 2;
    ctx.fillStyle = colors.dots;
    for (var b = 0; b < 5; b++) {
      var lo2 = b / 5, hi = (b + 1) / 5;
      ctx.beginPath();
      for (var i = 0; i < LAND; i++) {
        var z = projZ[i];
        if (z <= lo2 || z > hi) continue;
        ctx.rect(X + projX[i] * RR - half, Y - projY[i] * RR - half, size, size);
      }
      // Steeper than linear: the limb is where the dots crowd together, so
      // it is where they have to be faintest.
      ctx.globalAlpha = (0.08 + 0.82 * Math.pow((b + 0.5) / 5, 1.3)) * fade * (colors.light ? 0.9 : 1);
      ctx.fill();
    }

    // Reports in flight.
    ctx.strokeStyle = colors.accent; ctx.lineCap = "round";
    for (var a = arcs.length - 1; a >= 0; a--) {
      var arc = arcs[a], e = now - arc.born;
      var head = easeInOut(Math.min(1, e / arc.dur));
      var tail = easeInOut(Math.max(0, Math.min(1, (e - arc.dur * 0.45) / arc.dur)));
      if (head >= 1 && !arc.arrived) { arc.arrived = true; pulses.push({ at: arc.to, born: now }); }
      if (tail >= 1) { arcs.splice(a, 1); continue; }
      ctx.lineWidth = 1.2 * DPR; drawArc(arc, head, tail, 0.55);
      ctx.lineWidth = 2 * DPR; drawArc(arc, head, Math.max(tail, head - 0.12), 1);
      if (tail <= 0) {                     // where it came from
        var o = arcPoint(arc, 0);
        if (o) { ctx.globalAlpha = 0.9 * fade; ctx.fillStyle = colors.accent;
          ctx.beginPath(); ctx.arc(o[0] * DPR, o[1] * DPR, 1.8 * DPR, 0, Math.PI * 2); ctx.fill(); }
      }
    }

    // The console: a steady point, and a ring each time something lands.
    if (hub >= 0 && projZ[hub] > 0) {
      var hx = X + projX[hub] * RR, hy = Y - projY[hub] * RR;
      for (var q = pulses.length - 1; q >= 0; q--) {
        var pu = pulses[q], f = (now - pu.born) / 1600;
        if (f >= 1) { pulses.splice(q, 1); continue; }
        if (pu.at !== hub) continue;
        ctx.globalAlpha = 0.85 * (1 - f) * fade; ctx.strokeStyle = colors.accent; ctx.lineWidth = 1.4 * DPR;
        ctx.beginPath(); ctx.arc(hx, hy, (3 + f * 18) * DPR, 0, Math.PI * 2); ctx.stroke();
      }
      var halo = ctx.createRadialGradient(hx, hy, 0, hx, hy, 10 * DPR);
      halo.addColorStop(0, "rgba(" + colors.accentRgb + ",.55)");
      halo.addColorStop(1, "rgba(" + colors.accentRgb + ",0)");
      ctx.globalAlpha = fade; ctx.fillStyle = halo;
      ctx.beginPath(); ctx.arc(hx, hy, 10 * DPR, 0, Math.PI * 2); ctx.fill();
      ctx.fillStyle = colors.accent;
      ctx.beginPath(); ctx.arc(hx, hy, 2.6 * DPR, 0, Math.PI * 2); ctx.fill();
    }
    ctx.globalAlpha = 1;
  }

  function frame(now) {
    raf = 0;
    if (!running) return;
    var dt = last ? Math.min(100, now - last) : 16;
    // About 40 frames a second is plenty for something this slow, and
    // leaves the machine alone while someone types a password.
    if (last && now - last < 24) { raf = requestAnimationFrame(frame); return; }
    last = now;
    spin += SPIN * dt / 1000;
    if (now >= nextSpawn) { spawn(now, Math.random); nextSpawn = now + 650 + Math.random() * 700; }
    draw(now);
    raf = requestAnimationFrame(frame);
  }

  // A fixed, seeded still for reduced motion: same picture every time.
  function still() {
    var seed = 7;
    var rnd = function () { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
    arcs = []; pulses = []; hub = -1;
    projectLand();
    var t0 = 100000;
    for (var i = 0; i < 6; i++) spawn(t0, rnd);
    // Freeze each arc mid-flight, staggered, so the frame shows motion
    // without moving.
    arcs.forEach(function (a, n) { a.born = t0 - a.dur * (0.55 + n * 0.1); a.arrived = true; });
    draw(t0);
  }

  function shouldRun() {
    return !screenEl.hidden && !document.hidden && !(reduceQuery && reduceQuery.matches);
  }
  function update() {
    if (screenEl.hidden) { stop(); return; }
    layout(); readColors();
    if (shouldRun()) start(); else { stop(); if (!screenEl.hidden) still(); }
  }
  function start() {
    if (running) return;
    running = true; last = 0;
    if (!raf) raf = requestAnimationFrame(frame);
  }
  function stop() {
    running = false;
    if (raf) { cancelAnimationFrame(raf); raf = 0; }
  }

  new MutationObserver(update).observe(screenEl, { attributes: true, attributeFilter: ["hidden"] });
  new MutationObserver(function () { readColors(); if (!running && !screenEl.hidden) still(); })
    .observe(document.documentElement, { attributes: true, attributeFilter: ["data-palette", "data-theme", "style"] });
  document.addEventListener("visibilitychange", update);
  if (reduceQuery) {
    if (reduceQuery.addEventListener) reduceQuery.addEventListener("change", update);
    else if (reduceQuery.addListener) reduceQuery.addListener(update);
  }
  var resizeTimer = 0;
  window.addEventListener("resize", function () {
    clearTimeout(resizeTimer);
    resizeTimer = setTimeout(function () { if (!screenEl.hidden) { layout(); if (!running) still(); } }, 80);
  });
  update();
})();
