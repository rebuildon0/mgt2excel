/* MGT2Excel 変換ワーカー
 * Pyodide(ブラウザ内 Python)上で mgt2excel.py の convert() をそのまま実行する。
 * ファイルはすべてワーカー内の仮想ファイルシステムで処理され、外部送信されない。
 */
importScripts("https://cdn.jsdelivr.net/pyodide/v0.26.4/full/pyodide.js");

let pyodide = null;

async function init() {
  pyodide = await loadPyodide();
  await pyodide.loadPackage("micropip");
  const micropip = pyodide.pyimport("micropip");
  await micropip.install("openpyxl");
  const resp = await fetch("mgt2excel.py?v=" + Date.now());
  if (!resp.ok) throw new Error("mgt2excel.py の取得に失敗しました");
  pyodide.FS.writeFile("/home/pyodide/mgt2excel.py", await resp.text());
  // import 確認(構文エラー等はここで検出)
  pyodide.runPython("import sys; sys.path.insert(0, '/home/pyodide'); import mgt2excel");
  postMessage({ type: "ready" });
}

function convert(msg) {
  pyodide.FS.writeFile("/tmp/model.mgt", new Uint8Array(msg.mgt));
  pyodide.FS.writeFile("/tmp/model.anl", new Uint8Array(msg.anl));
  pyodide.globals.set("js_log", (s) => postMessage({ type: "log", text: String(s) }));
  pyodide.globals.set("opt_supports", msg.supports);
  pyodide.globals.set("opt_releases", msg.releases);
  pyodide.globals.set("opt_units", msg.units);
  pyodide.runPython(`
import mgt2excel
mgt2excel.convert(
    "/tmp/model.mgt", "/tmp/model.anl", "/tmp/out.xlsx",
    split_at_supports=bool(opt_supports),
    split_at_releases=bool(opt_releases),
    convert_units=bool(opt_units),
    log=js_log,
)
`);
  const bytes = pyodide.FS.readFile("/tmp/out.xlsx");
  // 一時ファイルを掃除
  for (const p of ["/tmp/model.mgt", "/tmp/model.anl", "/tmp/out.xlsx"]) {
    try { pyodide.FS.unlink(p); } catch (e) { /* noop */ }
  }
  postMessage({ type: "done", bytes: bytes.buffer, filename: msg.filename }, [bytes.buffer]);
}

self.onmessage = async (e) => {
  const msg = e.data;
  try {
    if (msg.type === "init") {
      await init();
    } else if (msg.type === "convert") {
      convert(msg);
    }
  } catch (err) {
    postMessage({ type: "error", text: (err && err.message) || String(err) });
  }
};
