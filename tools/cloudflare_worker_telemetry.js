/**
 * OLT MONITOR telemetry + remote license (Module Worker)
 *
 * Bind KV: TELEMETRY_KV
 * STATS_TOKEN = admin token (stats + set license)
 *
 * POST /v1/ping          — app ping (response may include license)
 * GET  /v1/license?install_id=&hwid=
 * POST /v1/license       — admin set {token, install_id, mode, max_olts}
 * POST /v1/command       — admin {token, install_id, action: restart}
 * GET  /v1/stats?days=30&token=
 */

const STATS_TOKEN = "GANTI_DENGAN_TOKEN_RAHASIA";

export default {
  async fetch(request, env) {
    const url = new URL(request.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    if (request.method === "OPTIONS") return cors(new Response(null, { status: 204 }));
    try {
      if (path === "/v1/ping" && request.method === "POST")
        return cors(await handlePing(request, env));
      if (path === "/v1/license" && request.method === "GET")
        return cors(await handleLicenseGet(url, env));
      if (path === "/v1/license" && request.method === "POST")
        return cors(await handleLicenseSet(request, env));
      if (path === "/v1/license/set" && request.method === "GET")
        return cors(await handleLicenseSetGet(url, env));
      if (path === "/v1/command" && request.method === "POST")
        return cors(await handleCommand(request, env));
      if (path === "/v1/stats" && request.method === "GET")
        return cors(await handleStats(request, env, url));
      if (path === "/" || path === "/health")
        return cors(json({ ok: true, service: "olt-monitor-telemetry" }));
      return cors(json({ ok: false, error: "not found" }, 404));
    } catch (e) {
      return cors(json({ ok: false, error: String(e.message || e) }, 500));
    }
  },
};

async function getLicense(env, installId) {
  if (!installId) return null;
  const raw = await env.TELEMETRY_KV.get(`license:${installId}`);
  if (!raw) return null;
  try { return JSON.parse(raw); } catch { return null; }
}

async function handlePing(request, env) {
  if (!env.TELEMETRY_KV) return json({ ok: false, error: "TELEMETRY_KV missing" }, 500);
  let body;
  try { body = await request.json(); } catch { return json({ ok: false, error: "invalid json" }, 400); }
  if (body.app !== "olt-monitor") return json({ ok: false, error: "unknown app" }, 400);
  const installId = String(body.install_id || body.hwid || "").slice(0, 128);
  if (!installId) return json({ ok: false, error: "missing install_id" }, 400);

  const now = Math.floor(Date.now() / 1000);
  // Pertahankan grant admin jika ada
  let prevGrant = {};
  try {
    const prevRaw = await env.TELEMETRY_KV.get(`install:${installId}`);
    if (prevRaw) {
      const prev = JSON.parse(prevRaw);
      if (prev.grant_mode) prevGrant.grant_mode = prev.grant_mode;
      if (prev.grant_max_olts) prevGrant.grant_max_olts = prev.grant_max_olts;
    }
  } catch {}
  const licNow = (await getLicense(env, installId)) || {};
  if (licNow.mode) {
    prevGrant.grant_mode = licNow.mode;
    prevGrant.grant_max_olts = licNow.max_olts || (licNow.mode === "full" ? 5 : 3);
  }

  const record = {
    install_id: installId,
    hwid: String(body.hwid || "").slice(0, 64),
    version: String(body.version || "").slice(0, 32),
    license_mode: String(body.license_mode || "").slice(0, 16),
    license_max_olts: Number(body.license_max_olts) || 0,
    olt_count: Number(body.olt_count) || 0,
    email: String(body.email || "").slice(0, 120).toLowerCase(),
    full_name: String(body.full_name || "").slice(0, 80),
    company: String(body.company || "").slice(0, 80),
    whatsapp: String(body.whatsapp || "").slice(0, 32),
    platform: body.platform || {},
    ts: Number(body.ts) || now,
    recv_at: now,
    ...prevGrant,
  };
  await env.TELEMETRY_KV.put(`install:${installId}`, JSON.stringify(record), { expirationTtl: 60 * 60 * 24 * 90 });

  let ids = [];
  try {
    const raw = await env.TELEMETRY_KV.get("index:installs");
    if (raw) ids = JSON.parse(raw);
  } catch {}
  if (!ids.includes(installId)) {
    ids.push(installId);
    if (ids.length > 5000) ids = ids.slice(-5000);
    await env.TELEMETRY_KV.put("index:installs", JSON.stringify(ids));
  }

  const lic = (await getLicense(env, installId)) || { mode: "trial", max_olts: 3 };
  const commands = [];
  try {
    const cmdRaw = await env.TELEMETRY_KV.get(`cmd:${installId}`);
    if (cmdRaw) {
      const cmd = JSON.parse(cmdRaw);
      if (cmd && cmd.action === "restart") {
        commands.push("restart");
        // one-shot
        await env.TELEMETRY_KV.delete(`cmd:${installId}`);
      }
    }
  } catch {}
  return json({
    ok: true,
    license: { mode: lic.mode || "trial", max_olts: lic.max_olts || 1 },
    commands,
  });
}

async function handleLicenseGet(url, env) {
  const installId = url.searchParams.get("install_id") || "";
  const hwid = url.searchParams.get("hwid") || "";
  let lic = await getLicense(env, installId);
  if (!lic && hwid) {
    try {
      const raw = await env.TELEMETRY_KV.get(`license:hwid:${hwid}`);
      if (raw) lic = JSON.parse(raw);
    } catch {}
  }
  if (!lic) lic = { mode: "trial", max_olts: 3 };
  return json({
    ok: true,
    license: {
      mode: lic.mode || "trial",
      max_olts: Number(lic.max_olts) || ((lic.mode || "trial") === "full" ? 5 : 3),
    },
  });
}

async function handleLicenseSet(request, env) {
  let body;
  try { body = await request.json(); } catch { return json({ ok: false, error: "invalid json" }, 400); }
  const token = String(body.token || "");
  if (!STATS_TOKEN || token !== STATS_TOKEN) return json({ ok: false, error: "unauthorized" }, 401);
  const installId = String(body.install_id || "").trim().slice(0, 128);
  if (!installId) return json({ ok: false, error: "install_id required" }, 400);
  let mode = String(body.mode || "trial").toLowerCase().trim();
  if (mode !== "full") mode = "trial";
  let maxOlts = parseInt(body.max_olts || (mode === "full" ? 5 : 3), 10);
  if (isNaN(maxOlts)) maxOlts = mode === "full" ? 5 : 3;
  if (mode === "trial") maxOlts = 3;
  else {
    if (maxOlts < 5) maxOlts = 5;
    if (maxOlts % 5) maxOlts = Math.ceil(maxOlts / 5) * 5;
  }
  const rec = {
    mode,
    max_olts: maxOlts,
    updated_at: Math.floor(Date.now() / 1000),
    install_id: installId,
  };
  await env.TELEMETRY_KV.put(`license:${installId}`, JSON.stringify(rec));

  // Mirror ke HWID
  let hwid = String(body.hwid || "").trim().slice(0, 64);
  try {
    const instRaw = await env.TELEMETRY_KV.get(`install:${installId}`);
    if (instRaw) {
      const row = JSON.parse(instRaw);
      if (!hwid && row.hwid) hwid = String(row.hwid);
      row.grant_mode = mode;
      row.grant_max_olts = maxOlts;
      await env.TELEMETRY_KV.put(`install:${installId}`, JSON.stringify(row), { expirationTtl: 60 * 60 * 24 * 90 });
    }
  } catch (e) {}
  if (hwid) {
    await env.TELEMETRY_KV.put(`license:hwid:${hwid}`, JSON.stringify(rec));
  }
  return json({ ok: true, install_id: installId, license: rec });
}


async function handleLicenseSetGet(url, env) {
  const token = url.searchParams.get("token") || "";
  if (!STATS_TOKEN || token !== STATS_TOKEN) {
    return json({ ok: false, error: "unauthorized" }, 401);
  }
  const installId = String(url.searchParams.get("install_id") || "").trim().slice(0, 128);
  if (!installId) {
    return json({ ok: false, error: "install_id required" }, 400);
  }
  let mode = String(url.searchParams.get("mode") || "trial").toLowerCase().trim();
  if (mode !== "full") mode = "trial";
  let maxOlts = parseInt(url.searchParams.get("max_olts") || (mode === "full" ? "5" : "3"), 10);
  if (isNaN(maxOlts)) maxOlts = mode === "full" ? 5 : 3;
  if (mode === "trial") {
    maxOlts = 3;
  } else {
    if (maxOlts < 5) maxOlts = 5;
    if (maxOlts % 5) maxOlts = Math.ceil(maxOlts / 5) * 5;
  }
  const rec = {
    mode,
    max_olts: maxOlts,
    updated_at: Math.floor(Date.now() / 1000),
    install_id: installId,
  };
  await env.TELEMETRY_KV.put(`license:${installId}`, JSON.stringify(rec));

  let hwid = String(url.searchParams.get("hwid") || "").trim().slice(0, 64);
  try {
    const instRaw = await env.TELEMETRY_KV.get(`install:${installId}`);
    if (instRaw) {
      const row = JSON.parse(instRaw);
      if (!hwid && row.hwid) hwid = String(row.hwid);
      row.grant_mode = mode;
      row.grant_max_olts = maxOlts;
      await env.TELEMETRY_KV.put(
        `install:${installId}`,
        JSON.stringify(row),
        { expirationTtl: 60 * 60 * 24 * 90 }
      );
    }
  } catch (e) {}

  if (hwid) {
    await env.TELEMETRY_KV.put(`license:hwid:${hwid}`, JSON.stringify(rec));
  }

  const days = url.searchParams.get("days") || "30";
  const loc =
    `/v1/stats?days=${days}&token=${encodeURIComponent(token)}` +
    `&_ok=${encodeURIComponent(mode + "-" + maxOlts)}`;
  return new Response(null, { status: 302, headers: { Location: loc } });
}

async function handleCommand(request, env) {
  let body = {};
  const ct = (request.headers.get("Content-Type") || "").toLowerCase();
  try {
    if (ct.includes("application/json")) {
      body = await request.json();
    } else {
      const fd = await request.formData();
      body = Object.fromEntries(fd.entries());
    }
  } catch {
    return json({ ok: false, error: "invalid body" }, 400);
  }
  const token = String(body.token || "");
  if (!STATS_TOKEN || token !== STATS_TOKEN) return json({ ok: false, error: "unauthorized" }, 401);
  const installId = String(body.install_id || "").slice(0, 128);
  const action = String(body.action || "").toLowerCase();
  if (!installId) return json({ ok: false, error: "install_id required" }, 400);
  if (action !== "restart") return json({ ok: false, error: "unsupported action" }, 400);
  await env.TELEMETRY_KV.put(
    `cmd:${installId}`,
    JSON.stringify({ action: "restart", at: Math.floor(Date.now() / 1000) }),
    { expirationTtl: 60 * 60 * 6 }
  );
  // If form post from browser, redirect back to stats
  if (!ct.includes("application/json")) {
    return new Response(null, {
      status: 302,
      headers: { Location: "/v1/stats?days=30&token=" + encodeURIComponent(token) + "&_ok=restart" },
    });
  }
  return json({ ok: true, install_id: installId, action: "restart", msg: "Menunggu ping berikutnya dari app" });
}

async function handleStats(request, env, url) {

  if (!env.TELEMETRY_KV) return json({ ok: false, error: "TELEMETRY_KV missing" }, 500);
  const token = url.searchParams.get("token") || "";
  if (!STATS_TOKEN || token !== STATS_TOKEN) return json({ ok: false, error: "unauthorized" }, 401);
  const days = Math.min(90, Math.max(1, parseInt(url.searchParams.get("days") || "30", 10)));
  const cutoff = Math.floor(Date.now() / 1000) - days * 86400;
  const wantJson = url.searchParams.get("format") === "json" ||
    (request.headers.get("Accept") || "").includes("application/json");

  let ids = [];
  try {
    const raw = await env.TELEMETRY_KV.get("index:installs");
    if (raw) ids = JSON.parse(raw);
  } catch {}

  const rows = [];
  for (const id of ids) {
    const raw = await env.TELEMETRY_KV.get(`install:${id}`);
    if (!raw) continue;
    try {
      const row = JSON.parse(raw);
      const last = row.recv_at || row.ts || 0;
      if (last < cutoff) continue;
      const lic = (await getLicense(env, id)) || {};
      rows.push({
        install_id: id,
        last,
        version: row.version || "",
        mode: (lic && lic.mode) || row.grant_mode || "trial",
        olt_count: row.olt_count ?? "",
        max_olts: (lic && lic.max_olts) || row.grant_max_olts || ((lic && lic.mode) === "full" || row.grant_mode === "full" ? 5 : 3),
        platform: (row.platform && row.platform.system) || "",
        email: row.email || "",
        full_name: row.full_name || "",
        company: row.company || "",
        whatsapp: row.whatsapp || "",
        hwid: row.hwid || "",
      });
    } catch {}
  }
  rows.sort((a, b) => (b.last || 0) - (a.last || 0));

  if (wantJson) {
    const installs = {};
    for (const r of rows) installs[r.install_id] = r;
    return json({ ok: true, days, active_installs: rows.length, installs });
  }

  const fmt = (ts) => {
    try { return new Date(ts * 1000).toLocaleString("id-ID", { timeZone: "Asia/Jakarta" }); }
    catch { return "-"; }
  };
  const tokenQ = encodeURIComponent(token);
  const tr = rows.map((r, i) => {
    const id = r.install_id;
    const curMax = Number(r.max_olts) || 5;
    return `<tr>
      <td>${i + 1}</td>
      <td>${esc(r.full_name)}</td>
      <td>${esc(r.company)}</td>
      <td>${esc(r.email)}</td>
      <td>${esc(r.whatsapp)}</td>
      <td>
        <span class="badge ${r.mode === "full" ? "full" : "trial"}">${esc(r.mode)}</span>
        <div class="acts">
          <form method="get" action="/v1/license/set" class="lic-form">
            <input type="hidden" name="token" value="${esc(token)}">
            <input type="hidden" name="install_id" value="${esc(id)}">
            <input type="hidden" name="hwid" value="${esc(r.hwid || '')}">
            <input type="hidden" name="mode" value="full">
            <label class="olts-lab">OLT</label>
            <input type="number" name="max_olts" min="5" step="5" value="${curMax >= 5 ? curMax : 5}" class="olts-in">
            <button type="submit" class="btn-act">Full</button>
          </form>
          <a class="btn-act" href="/v1/license/set?token=${tokenQ}&install_id=${encodeURIComponent(id)}&mode=trial&max_olts=3&hwid=${encodeURIComponent(r.hwid||'')}">Trial</a>
          <a class="btn-act" href="/v1/license?install_id=${encodeURIComponent(id)}&hwid=${encodeURIComponent(r.hwid||'')}">Cek grant</a>
        </div>
      </td>
      <td>${esc(String(r.olt_count))} / ${esc(String(r.max_olts))}</td>
      <td>${esc(r.version)}</td>
      <td>${fmt(r.last)}</td>
      <td class="mono" title="${esc(r.hwid || '')}">${esc((r.hwid || "-").toString().slice(0, 19))}</td>
      <td class="mono" title="${esc(id)}">${esc(String(id).slice(0, 12))}…</td>
    </tr>`;
  }).join("");

  const html = `<!DOCTYPE html>
<html lang="id"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>OLT MONITOR — Pengguna</title>
<style>
body{margin:0;background:#0f172a;color:#e2e8f0;font-family:system-ui,sans-serif}
.wrap{max-width:1200px;margin:0 auto;padding:24px 16px}
h1{font-size:1.25rem;margin:0 0 4px}
.sub{color:#94a3b8;margin-bottom:16px;font-size:.9rem}
.stat{display:inline-block;background:#1e293b;border-radius:8px;padding:10px 16px;margin:0 8px 16px 0}
.stat b{font-size:1.4rem;color:#38bdf8}
table{width:100%;border-collapse:collapse;background:#1e293b;border-radius:12px;overflow:hidden;font-size:.88rem}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid #334155;vertical-align:top}
th{background:#334155;color:#cbd5e1;white-space:nowrap}
.badge{padding:2px 8px;border-radius:999px;font-size:.75rem;font-weight:600}
.badge.full{background:#14532d;color:#86efac}
.badge.trial{background:#713f12;color:#fde68a}
.acts{display:flex;flex-wrap:wrap;align-items:center;gap:4px;margin-top:6px}
.lic-form{display:inline-flex;align-items:center;gap:4px;margin:0}
.acts button{font-size:.75rem;padding:3px 10px;border-radius:6px;border:0;cursor:pointer;background:#334155;color:#e2e8f0}
.acts button:hover{background:#475569}
.olts-lab{font-size:.7rem;color:#94a3b8}
.olts-in{width:64px;padding:3px 6px;border-radius:6px;border:1px solid #475569;background:#0f172a;color:#e2e8f0;font-size:.8rem}
.mono{font-family:ui-monospace,monospace;font-size:.8rem;color:#94a3b8}
a{color:#38bdf8}
#msg{margin:8px 0;color:#86efac;font-weight:600}
.logbox{background:#020617;border:1px solid #334155;border-radius:10px;padding:12px;margin-bottom:16px;max-height:220px;overflow:auto}
.log-title{font-size:.8rem;color:#94a3b8;margin-bottom:6px}
#log{margin:0;font-family:ui-monospace,monospace;font-size:.78rem;color:#cbd5e1;white-space:pre-wrap;word-break:break-all}

</style></head><body>
<div class="wrap">
<h1>OLT MONITOR — Pengguna aktif</h1>
<p class="sub">${days} hari · atur jumlah OLT lalu klik <b>Full</b> / <b>Trial</b> ·
<a href="?days=${days}&token=${tokenQ}&format=json">JSON</a></p>
<div id="msg" style="color:#86efac;font-weight:600;margin:8px 0">${url.searchParams.get("_ok") ? ("✓ Berhasil: " + url.searchParams.get("_ok") + " — refresh jika badge belum berubah") : ""}</div>
<div class="logbox">
  <div class="log-title">Cara aktivasi</div>
  <pre id="log">1. Isi angka OLT → klik Full
2. Halaman akan reload
3. Badge harus jadi hijau (full)
Jika gagal, buka link manual (ganti TOKEN & install_id):
/v1/license/set?token=TOKEN&install_id=INSTALL&mode=full&max_olts=50</pre>
</div>

<div class="stat"><div>Aktif</div><b>${rows.length}</b></div>
<div class="stat"><div>Full</div><b>${rows.filter(r=>r.mode==="full").length}</b></div>
<div class="stat"><div>Trial</div><b>${rows.filter(r=>r.mode!=="full").length}</b></div>
<table>
<thead><tr>
<th>#</th><th>Nama</th><th>Perusahaan</th><th>Email</th><th>WA</th>
<th>License</th><th>OLT</th><th>Versi</th><th>Terakhir</th><th>HWID</th><th>Install</th>
</tr></thead>
<tbody>${tr || '<tr><td colspan="11">Belum ada data</td></tr>'}</tbody>
</table>
</div>

</body></html>`;
  return new Response(html, { headers: { "Content-Type": "text/html; charset=utf-8" } });
}

function json(data, status = 200) {
  return new Response(JSON.stringify(data), {
    status,
    headers: { "Content-Type": "application/json" },
  });
}
function cors(res) {
  const h = new Headers(res.headers);
  h.set("Access-Control-Allow-Origin", "*");
  h.set("Access-Control-Allow-Methods", "GET, POST, OPTIONS");
  h.set("Access-Control-Allow-Headers", "Content-Type");
  return new Response(res.body, { status: res.status, headers: h });
}
function esc(s) {
  return String(s ?? "").replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");
}
