/**
 * SVSL ERP – Windows desktop app (Electron).
 *
 * "This computer is the server" (default): starts a private PostgreSQL database and the ERP server that are
 * bundled with the installer, then shows the ERP in a window. Phones on the same Wi-Fi use the Android app
 * (or a browser) with this computer's address, shown under Help → Phone connection.
 * "Connect to a server": opens the ERP running on another computer or in the cloud (no local data).
 *
 * Database:  %LOCALAPPDATA%\SVSL ERP\Database   (kept out of OneDrive-synced folders)
 * Files and backups: Documents\SVSL ERP\Files, Documents\SVSL ERP\Backup   (survive uninstall/updates)
 */
const { app, BrowserWindow, Menu, dialog, ipcMain, shell, clipboard } = require("electron");
const path = require("node:path");
const fs = require("node:fs");
const os = require("node:os");
const crypto = require("node:crypto");
const http = require("node:http");
const { spawn, execFile } = require("node:child_process");

const VERSION = app.getVersion();
const WIN = process.platform === "win32";
const EXE = WIN ? ".exe" : "";
const APP_PORT = Number(process.env.SVSL_PORT || 8000);
const PG_PORT = Number(process.env.SVSL_PG_PORT || 54329);

const userData = app.getPath("userData");
const configFile = path.join(userData, "config.json");
const localData = path.join(process.env.LOCALAPPDATA || userData, "SVSL ERP");
const pgData = path.join(localData, "Database");
const home = path.join(app.getPath("documents"), "SVSL ERP");
const filesDir = path.join(home, "Files");
const backupDir = path.join(home, "Backup");
const logDir = path.join(localData, "Logs");

// Bundled resources: packaged → resources/, development → desktop/res/
const resDir = app.isPackaged ? process.resourcesPath : path.join(__dirname, "res");
const serverExe = process.env.SVSL_SERVER_EXE || path.join(resDir, "server", "svsl-server" + EXE);
const pgBin = process.env.SVSL_PG_BIN || path.join(resDir, "pgsql", "bin");
const webDir = path.join(resDir, "web");

let win = null;
let config = null;
let serverProc = null;
let quitting = false;

app.userAgentFallback = `${app.userAgentFallback} SVSLApp-Desktop/${VERSION}`;
if (!app.requestSingleInstanceLock()) app.quit();
app.on("second-instance", () => { if (win) { if (win.isMinimized()) win.restore(); win.focus(); } });

function readConfig() { try { return JSON.parse(fs.readFileSync(configFile, "utf8")); } catch { return null; } }
function writeConfig(c) { fs.mkdirSync(userData, { recursive: true }); fs.writeFileSync(configFile, JSON.stringify(c, null, 2), { mode: 0o600 }); }
function log(msg) { fs.mkdirSync(logDir, { recursive: true }); fs.appendFileSync(path.join(logDir, "desktop.log"), `${new Date().toISOString()} ${msg}\n`); }
function status(text) { if (win && !win.isDestroyed()) win.webContents.send("svsl:status", text); log(text); }

function lanAddresses() {
  const out = [];
  for (const list of Object.values(os.networkInterfaces())) for (const a of list || []) if (a.family === "IPv4" && !a.internal) out.push(a.address);
  return out;
}

function run(file, args, env = {}, opts = {}) {
  return new Promise((resolve, reject) => {
    execFile(file, args, { env: { ...process.env, ...env }, windowsHide: true, timeout: opts.timeout || 180000, maxBuffer: 10 * 1024 * 1024 }, (err, stdout, stderr) => {
      log(`$ ${path.basename(file)} ${args.join(" ")}\n${stdout}${stderr}`);
      if (err) reject(new Error(`${path.basename(file)} failed: ${(stderr || stdout || err.message).toString().slice(-800)}`));
      else resolve(stdout.toString());
    });
  });
}

function waitForHealth(url, ms) {
  const until = Date.now() + ms;
  return new Promise((resolve, reject) => {
    const tick = () => {
      const req = http.get(`${url}/api/health`, (res) => { res.resume(); if (res.statusCode === 200) resolve(); else retry(); });
      req.on("error", retry);
      req.setTimeout(3000, () => req.destroy());
    };
    const retry = () => (Date.now() > until ? reject(new Error("The ERP server did not start. See the log in " + logDir)) : setTimeout(tick, 700));
    tick();
  });
}

function serverEnv() {
  return {
    DATABASE_URL: `postgresql+psycopg://svsl:${encodeURIComponent(config.dbPassword)}@127.0.0.1:${PG_PORT}/svsl_erp`,
    SECRET_KEY: config.secretKey,
    DATA_ENCRYPTION_KEY: config.encKey,
    STORAGE_DIR: filesDir,
    BACKUP_DIR: backupDir,
    FRONTEND_DIST: webDir,
    PG_DUMP_PATH: path.join(pgBin, "pg_dump" + EXE),
    HOST: "0.0.0.0",
    PORT: String(APP_PORT),
    PUBLIC_BASE_URL: `http://${lanAddresses()[0] || "localhost"}:${APP_PORT}`,
    CORS_ORIGINS: `http://localhost:${APP_PORT}`,
    RUN_SCHEDULER: "true",
    APP_ENV: "production",
    PYTHONIOENCODING: "utf-8",
  };
}

async function startDatabase(firstRun) {
  fs.mkdirSync(localData, { recursive: true });
  const pgEnv = { PGPASSWORD: config.dbPassword, LC_MESSAGES: "C" };
  if (!fs.existsSync(path.join(pgData, "PG_VERSION"))) {
    status("Creating the database (first start, about a minute)…");
    const pw = path.join(localData, "pw.tmp");
    fs.writeFileSync(pw, config.dbPassword, { mode: 0o600 });
    try {
      await run(path.join(pgBin, "initdb" + EXE), ["-D", pgData, "-U", "svsl", `--pwfile=${pw}`, "-E", "UTF8", "--locale=C", "-A", "scram-sha-256"], pgEnv);
    } finally { fs.rmSync(pw, { force: true }); }
  }
  status("Starting the database…");
  const running = await run(path.join(pgBin, "pg_ctl" + EXE), ["status", "-D", pgData], pgEnv).then(() => true, () => false);
  if (!running) {
    await run(path.join(pgBin, "pg_ctl" + EXE), ["start", "-w", "-t", "120", "-D", pgData, "-l", path.join(logDir, "postgres.log"), "-o", `-p ${PG_PORT} -h 127.0.0.1${WIN ? "" : ` -k "${localData}"`}`], pgEnv);
  }
  const hasDb = await run(path.join(pgBin, "psql" + EXE), ["-h", "127.0.0.1", "-p", String(PG_PORT), "-U", "svsl", "-d", "postgres", "-tAc", "SELECT 1 FROM pg_database WHERE datname='svsl_erp'"], pgEnv);
  if (!hasDb.trim()) await run(path.join(pgBin, "createdb" + EXE), ["-h", "127.0.0.1", "-p", String(PG_PORT), "-U", "svsl", "svsl_erp"], pgEnv);
}

async function startServerMode() {
  fs.mkdirSync(filesDir, { recursive: true });
  fs.mkdirSync(backupDir, { recursive: true });
  await startDatabase();
  status("Updating the database structure…");
  const env = serverEnv();
  await run(serverExe, ["migrate"], env);
  if (!config.seeded) {
    const adminPassword = "Svsl@" + crypto.randomBytes(6).toString("base64url");
    await run(serverExe, ["seed"], { ...env, INITIAL_ADMIN_PASSWORD: adminPassword });
    config.seeded = true;
    config.pendingAdminPassword = adminPassword;
    writeConfig(config);
  } else {
    await run(serverExe, ["seed"], env); // idempotent: adds reference data introduced by updates
  }
  status("Starting the ERP server…");
  const out = fs.openSync(path.join(logDir, "server.log"), "a");
  serverProc = spawn(serverExe, ["serve"], { env: { ...process.env, ...env }, windowsHide: true, stdio: ["ignore", out, out] });
  serverProc.on("exit", (code) => {
    log(`server exited ${code}`);
    serverProc = null;
    if (!quitting) dialog.showErrorBox("SVSL ERP", `The ERP server stopped unexpectedly (code ${code}). Restart the app. Log: ${logDir}`);
  });
  await waitForHealth(`http://127.0.0.1:${APP_PORT}`, 90000);
  await win.loadURL(`http://localhost:${APP_PORT}/`);
  if (config.pendingAdminPassword) {
    const pw = config.pendingAdminPassword;
    const r = await dialog.showMessageBox(win, {
      type: "info", title: "First sign-in", buttons: ["Copy password", "OK"], defaultId: 0,
      message: `Sign in with\n\nUsername:  admin\nPassword:  ${pw}`,
      detail: "Write this down now – it is shown only once. You will be asked to choose your own password after signing in.\n\nAlso use File → Save security keys and keep that file with your backups.",
    });
    if (r.response === 0) clipboard.writeText(pw);
    delete config.pendingAdminPassword;
    writeConfig(config);
  }
}

async function stopAll() {
  if (serverProc) {
    const pid = serverProc.pid;
    if (WIN) await run("taskkill", ["/pid", String(pid), "/T", "/F"]).catch(() => {});
    else serverProc.kill();
  }
  if (config?.mode === "server" && fs.existsSync(path.join(pgData, "PG_VERSION"))) {
    await run(path.join(pgBin, "pg_ctl" + EXE), ["stop", "-D", pgData, "-m", "fast", "-w"], { PGPASSWORD: config.dbPassword }).catch(() => {});
  }
}

async function launch() {
  if (config.mode === "client") return win.loadURL(config.url);
  await win.loadFile(path.join(__dirname, "starting.html"));
  try {
    await startServerMode();
  } catch (e) {
    log(`START FAILED ${e.stack || e}`);
    const r = await dialog.showMessageBox(win, { type: "error", title: "SVSL ERP could not start", buttons: ["Open log folder", "Close"], message: "SVSL ERP could not start.", detail: String(e.message || e) });
    if (r.response === 0) await shell.openPath(logDir);
  }
}

ipcMain.handle("svsl:setup-info", () => ({ version: VERSION, home, port: APP_PORT }));
ipcMain.handle("svsl:test-url", async (_e, url) => {
  try { await waitForHealth(url.replace(/\/+$/, ""), 6000); return { ok: true }; } catch { return { ok: false, message: `Cannot reach ${url}` }; }
});
ipcMain.handle("svsl:setup-save", async (_e, c) => {
  const prev = readConfig() || {};
  if (c.mode === "client") {
    let url = String(c.url || "").trim().replace(/\/+$/, "");
    if (!url) return { ok: false, message: "Enter the server address" };
    if (!/^https?:\/\//i.test(url)) url = "http://" + url;
    if (/^http:/i.test(url) && !/:\d+$/.test(url.replace(/^https?:\/\//i, "").split("/")[0])) url += ":8000";
    config = { ...prev, mode: "client", url, chooseAgain: false };
  } else {
    config = { ...prev, mode: "server", chooseAgain: false };
    // Secrets are created once and kept (switching modes never loses them).
    if (!config.dbPassword) config.dbPassword = crypto.randomBytes(24).toString("hex");
    if (!config.secretKey) config.secretKey = crypto.randomBytes(48).toString("base64url");
    if (!config.encKey) config.encKey = crypto.randomBytes(32).toString("base64").replace(/\+/g, "-").replace(/\//g, "_"); // Fernet key
  }
  writeConfig(config);
  launch();
  return { ok: true };
});
ipcMain.on("svsl:open-logs", () => shell.openPath(logDir));

function phoneInfo() {
  const ips = lanAddresses();
  const text = config?.mode === "server"
    ? (ips.length ? ips.map((ip) => `${ip}:${APP_PORT}`).join("\n") : "This computer is not connected to a network.")
    : config?.url || "-";
  dialog.showMessageBox(win, {
    type: "info", title: "Phone connection",
    message: config?.mode === "server" ? `On phones, open the SVSL ERP app and enter:\n\n${text}` : `This computer uses the ERP server at\n${text}`,
    detail: config?.mode === "server" ? "The phone must be on the same Wi-Fi/network as this computer, and this computer must stay switched on with SVSL ERP open. If phones cannot connect, allow \"SVSL ERP\" through Windows Firewall (the installer adds the rule for private networks)." : "",
  });
}

async function saveKeys() {
  if (config?.mode !== "server") return dialog.showMessageBox(win, { message: "Security keys exist only on the server computer." });
  const r = await dialog.showSaveDialog(win, { title: "Save security keys", defaultPath: path.join(app.getPath("documents"), "SVSL-ERP-security-keys.json") });
  if (r.canceled || !r.filePath) return;
  fs.writeFileSync(r.filePath, JSON.stringify({ note: "Keep this file private and with your backups. Needed to restore encrypted fields (Aadhaar, bank numbers) on another computer.", SECRET_KEY: config.secretKey, DATA_ENCRYPTION_KEY: config.encKey, saved: new Date().toISOString() }, null, 2));
  dialog.showMessageBox(win, { message: "Security keys saved.", detail: r.filePath });
}

function menu() {
  Menu.setApplicationMenu(Menu.buildFromTemplate([
    { label: "File", submenu: [
      { label: "Open backup folder", click: () => { fs.mkdirSync(backupDir, { recursive: true }); shell.openPath(backupDir); } },
      { label: "Backup && restore", click: () => win && config?.mode === "server" && win.loadURL(`http://localhost:${APP_PORT}/backup`) },
      { label: "Save security keys…", click: saveKeys },
      { type: "separator" }, { role: "quit" },
    ] },
    { label: "View", submenu: [{ role: "reload" }, { role: "zoomIn" }, { role: "zoomOut" }, { role: "resetZoom" }, { role: "togglefullscreen" }] },
    { label: "Help", submenu: [
      { label: "Phone connection", click: phoneInfo },
      { label: "Open log folder", click: () => { fs.mkdirSync(logDir, { recursive: true }); shell.openPath(logDir); } },
      { label: "Change mode / server address…", click: async () => {
        const r = await dialog.showMessageBox(win, { type: "warning", buttons: ["Cancel", "Change"], message: "Change how this computer uses SVSL ERP?", detail: "No data is deleted. The app restarts and shows the setup screen." });
        if (r.response === 1) { const c = readConfig() || {}; c.chooseAgain = true; writeConfig(c); app.relaunch(); app.quit(); }
      } },
      { label: `About SVSL ERP ${VERSION}`, click: () => dialog.showMessageBox(win, { type: "info", title: "About", message: `SVSL ERP ${VERSION}`, detail: `Sri Vengarai Suraj Logistics – Transport & Logistics ERP\n\nMode: ${config?.mode || "-"}\nFiles & backups: ${home}\nDatabase: ${pgData}` }) },
    ] },
  ]));
}

app.whenReady().then(async () => {
  menu();
  win = new BrowserWindow({
    width: 1400, height: 880, title: `SVSL ERP`, icon: path.join(__dirname, "icon.png"),
    webPreferences: { preload: path.join(__dirname, "preload.cjs"), contextIsolation: true, nodeIntegration: false, sandbox: true },
  });
  win.webContents.setWindowOpenHandler(({ url }) => {
    if (url.startsWith("blob:") || url.startsWith(`http://localhost:${APP_PORT}`) || (config?.mode === "client" && url.startsWith(config.url))) return { action: "allow" };
    shell.openExternal(url);
    return { action: "deny" };
  });
  config = readConfig();
  if (!config || config.chooseAgain || !config.mode) return win.loadFile(path.join(__dirname, "setup.html"));
  launch();
});

app.on("before-quit", async (e) => {
  if (quitting) return;
  quitting = true;
  e.preventDefault();
  await stopAll();
  app.exit(0);
});
app.on("window-all-closed", () => app.quit());
