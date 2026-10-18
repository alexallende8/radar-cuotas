// Simulador automático: ejecuta el MISMO modelo que index.html (sin navegador) y
// registra en datos/simulador.json las apuestas que el radar recomienda, con dinero ficticio.
// Lo lanza la tarea diaria de GitHub después de actualizar.py.
const fs = require("fs");
const path = require("path");
const vm = require("vm");

const ROOT = path.resolve(__dirname, "..");
const html = fs.readFileSync(path.join(ROOT, "index.html"), "utf8");
const scripts = [...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map((m) => m[1]);
const code = scripts[scripts.length - 1];

const ctx = vm.createContext({console, Intl, Date, Math, JSON});
vm.runInContext(code + "\n;globalThis.__api = {S, BUILTIN, applyFeed, recompute, simStats, newSim};", ctx);
const api = ctx.__api;
const S = api.S;

const feedPath = path.join(ROOT, "datos", "datos.json");
const simPath = path.join(ROOT, "datos", "simulador.json");

S.hist = JSON.parse(JSON.stringify(api.BUILTIN.hist));
S.fixtures = api.BUILTIN.fixtures.slice();
if (fs.existsSync(feedPath)) api.applyFeed(JSON.parse(fs.readFileSync(feedPath, "utf8")));
S.serverSim = null;
S.sim = fs.existsSync(simPath) ? JSON.parse(fs.readFileSync(simPath, "utf8")) : api.newSim();

const before = S.sim.bets.length;
const pendBefore = S.sim.bets.filter((b) => b.status === "pendiente").length;
api.recompute();                      // analiza, liquida lo terminado y registra lo nuevo
S.sim.generado = new Date().toISOString();
fs.writeFileSync(simPath, JSON.stringify(S.sim));

const st = api.simStats(S.sim);
const pendAfterOld = S.sim.bets.slice(0, before).filter((b) => b.status === "pendiente").length;
console.log(`Simulador: ${S.sim.bets.length - before} apuestas nuevas, ${pendBefore - pendAfterOld} liquidadas, ` +
            `saldo ${st.bank.toFixed(2)} € (inicio ${S.sim.bank0} €), pendientes ${st.nPend}.`);
