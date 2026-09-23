/**
 * Update Worker: simpan juga field email di record
 * (paste ke Cloudflare Worker yang sudah ada)
 *
 * Di handlePing, pastikan record mencakup:
 *   email: String(body.email || "").slice(0, 120).toLowerCase(),
 *
 * Di handleStats installs[id]:
 *   email: row.email || "",
 */
