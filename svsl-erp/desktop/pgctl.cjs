// Starts PostgreSQL with `pg_ctl start -w` and resolves when pg_ctl itself exits.
// The database server launched by pg_ctl inherits pg_ctl's output handles; on Windows they stay open for as long as the
// database runs, so waiting for the output to close (child_process.execFile) only returned at its timeout (3 minutes
// on every app start). pg_ctl therefore gets no output handles (the server writes to its own -l log file).
// Used by main.cjs, and run directly by the Windows CI smoke test: node pgctl.cjs <pg_ctl.exe> <max seconds> <args…>
const { spawn } = require("node:child_process");

function pgCtlStart(pgCtl, args, env = {}, timeoutMs = 150000) {
  return new Promise((resolve, reject) => {
    const started = Date.now();
    const p = spawn(pgCtl, args, { env: { ...process.env, ...env }, windowsHide: true, stdio: "ignore" });
    const timer = setTimeout(() => { p.kill(); reject(new Error(`pg_ctl did not finish within ${timeoutMs / 1000} s`)); }, timeoutMs);
    p.on("error", (e) => { clearTimeout(timer); reject(e); });
    p.on("exit", (code) => {
      clearTimeout(timer);
      const seconds = (Date.now() - started) / 1000;
      if (code === 0) resolve(seconds);
      else reject(Object.assign(new Error(`pg_ctl exited with code ${code}`), { seconds }));
    });
  });
}

module.exports = { pgCtlStart };

if (require.main === module) {
  const [pgCtl, maxSeconds, ...args] = process.argv.slice(2);
  pgCtlStart(pgCtl, args).then((s) => {
    console.log(`pg_ctl start finished in ${s.toFixed(1)} s`);
    if (s > Number(maxSeconds)) { console.error(`too slow (limit ${maxSeconds} s)`); process.exit(1); }
  }, (e) => { console.error(e.message); process.exit(1); });
}
