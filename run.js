/**
 * 汽水音乐脚本 · 一键运行 + 实时日志
 *
 * 用法：
 *   node run.js <手机IP>            # 启动并实时打印日志
 *   node run.js <手机IP> stop       # 停止
 *
 * 例：
 *   node run.js 192.168.1.20
 *
 * 环境变量（可选）：
 *   QISHUI_PROJECT  工程名，默认 qishui
 *   QISHUI_LOG      日志文件的绝对路径（自动探测失败时手动指定）
 *
 * 为什么读文件而不是订阅 WebSocket 日志：
 * 实测 10102 的 /log/ 通道时好时坏（连上了却收不到数据），
 * 文件是唯一稳定可靠的通道，而且脚本异常终止前的最后一行也能读到。
 */

const HOST = process.argv[2];
const ACTION = process.argv[3] || "run";
const PROJECT = process.env.QISHUI_PROJECT || "qishui";

if (!HOST || HOST === "-h" || HOST === "--help") {
  console.log("用法: node run.js <手机IP> [stop]");
  console.log("  手机IP 在 AScript App → 开发者选项 里能看到（形如 192.168.1.20）");
  process.exit(0);
}

const API = `http://${HOST}:9096`;

// 工程可能装在主空间(0)或应用分身(10)，逐个探测哪个能读到
const LOG_CANDIDATES = [
  process.env.QISHUI_LOG,
  `/storage/emulated/0/airscript/model/${PROJECT}/run.log`,
  `/storage/emulated/10/airscript/model/${PROJECT}/run.log`,
].filter(Boolean);

let LOG_PATH = LOG_CANDIDATES[0];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function readRaw(path) {
  const url = `${API}/api/file/get?path=${encodeURIComponent(path)}`;
  try {
    const r = await fetch(url);
    return await r.text();
  } catch (e) {
    return null;
  }
}

// 文件不存在时接口会返回 {"code":0,...}，用它区分「没内容」和「路径不对」
function missing(txt) {
  return txt === null || txt.startsWith('{"code":0');
}

async function pickLogPath() {
  for (const p of LOG_CANDIDATES) {
    const t = await readRaw(p);
    if (!missing(t)) {
      LOG_PATH = p;
      return true;
    }
  }
  return false;
}

async function main() {
  if (ACTION === "stop") {
    const r = await fetch(`${API}/api/model/stop?name=${PROJECT}`);
    console.log("停止:", await r.text());
    return;
  }

  console.log(`手机 ${HOST} · 工程 ${PROJECT}`);

  // 启动前先确认能连上、工程存在
  try {
    const list = await (await fetch(`${API}/api/model/getlist`)).text();
    if (!list.includes(PROJECT)) {
      console.error(`⚠️ 手机上没找到工程「${PROJECT}」`);
      console.error("   请先在 AScript App 里创建工程并上传代码（见 README 第二节）");
      console.error("   或用 QISHUI_PROJECT=你的工程名 指定");
      return;
    }
  } catch (e) {
    console.error(`⚠️ 连不上 http://${HOST}:9096`);
    console.error("   检查：手机和电脑同一 WiFi、AScript 已打开开发者选项、IP 是否正确");
    return;
  }

  const ok = await pickLogPath();
  if (!ok) {
    console.log("（日志文件还没生成，脚本首次运行后会自动创建）");
  } else {
    console.log(`日志文件: ${LOG_PATH}`);
  }

  let last = ok ? await readRaw(LOG_PATH) : "";
  if (missing(last)) last = "";
  console.log("正在启动...\n");

  const r = await fetch(`${API}/api/model/run?name=${PROJECT}`);
  const body = await r.text();
  if (!body.includes('"code":1')) {
    console.error("启动失败:", body);
    return;
  }

  let idle = 0;
  for (;;) {
    await sleep(800);

    if (!LOG_PATH || missing(await readRaw(LOG_PATH))) {
      await pickLogPath();
      continue;
    }
    const txt = await readRaw(LOG_PATH);
    if (missing(txt)) continue;

    if (txt.length < last.length) last = "";          // 文件被重写过，重新对齐
    if (txt.length > last.length) {
      process.stdout.write(txt.slice(last.length));
      last = txt;
      idle = 0;
    } else if (++idle > 60) {                          // 约 48 秒没有新内容
      console.log("\n（48 秒无新日志，脚本可能已结束）");
      return;
    }

    if (txt.includes("脚本退出")) {
      await sleep(600);
      const fin = await readRaw(LOG_PATH);
      if (!missing(fin) && fin.length > last.length) {
        process.stdout.write(fin.slice(last.length));
      }
      return;
    }
  }
}

main().catch((e) => {
  console.error("出错了:", e.message);
  console.error("检查：手机是否亮屏、AScript 是否在运行、IP 是否正确");
  process.exit(1);
});
