/* ============================================================
   微信表情 → Telegram 贴纸包 — 前端逻辑
   ============================================================ */
(function () {
  "use strict";

  // ---------- 全局状态 ----------
  let ITEMS = [];
  let SELECTED = new Set();
  let buildJobId = null;
  let lastRes = null;                       // 上次生成结果（static_count / anim_count / failures）
  let selPacks = { static: new Set(), anim: new Set() };  // 卡④「当前包」分包勾选
  let selPacksHist = { static: new Set(), anim: new Set() }; // 弹窗「历史包」分包勾选
  let historyItems = [];                    // 历史包列表

  // ---------- DOM 快捷引用 ----------
  const $ = (id) => document.getElementById(id);
  const el = {
    folder: $("folder"), dirPicker: $("dirPicker"), scanError: $("scanError"),
    stickerCard: $("stickerCard"), countInfo: $("countInfo"), filter: $("filter"),
    grid: $("grid"), selCount: $("selCount"),
    buildCard: $("buildCard"), packName: $("packName"),
    buildBtn: $("buildBtn"), progress: $("progress"), progressBar: $("progressBar"),
    result: $("result"), resultStats: $("resultStats"), dlBtn: $("dlBtn"), failList: $("failList"),
    uploadCard: $("uploadCard"), packSelect: $("packSelect"),
    histCard: $("histCard"), histOpenBtn: $("histOpenBtn"), histModal: $("histModal"),
    histClose: $("histClose"), histSelect: $("histSelect"), histTitle: $("histTitle"),
    histStaticName: $("histStaticName"), histAnimName: $("histAnimName"), histUpBtn: $("histUpBtn"),
    histPackSelect: $("histPackSelect"), histProgress: $("histProgress"), histBar: $("histBar"), histResult: $("histResult"),
    upTitle: $("upTitle"), envInfo: $("envInfo"), staticName: $("staticName"),
    animName: $("animName"), upBtn: $("upBtn"), upProgress: $("upProgress"),
    upBar: $("upBar"), upResult: $("upResult"),
    guideCard: $("guideCard"), viewer: $("viewer"), viewerImg: $("viewerImg"),
    overlay: $("overlay"), ovTitle: $("ovTitle"), ovSub: $("ovSub"), ovBar: $("ovBar"),
    miniProgress: $("miniProgress"), miniTitle: $("miniTitle"), miniBar: $("miniBar"), miniPct: $("miniPct"),
  };

  // ---------- 通用请求 ----------
  async function jsonPost(url, body) {
    const r = await fetch(url, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
    });
    const d = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(d.error || ("请求失败 (HTTP " + r.status + ")"));
    return d;
  }

  // ---------- 提示区 ----------
  function showScanError(msg) {
    el.scanError.style.display = msg ? "block" : "none";
    el.scanError.textContent = msg || "";
  }

  // ---------- 统一状态横幅（成功 / 警示 / 失败） ----------
  function escHtml(s) {
    return String(s == null ? "" : s)
      .replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;").replace(/'/g, "&#39;");
  }

  // kind: "ok"（绿✅）/ "warn"（橙⚠️）/ "err"（红❌）；detail 为已转义 HTML（可为空）
  function statusBanner(kind, title, detail) {
    const cfg = { ok: ["ok", "✅"], warn: ["warn", "⚠️"], err: ["err", "❌"] }[kind] || ["err", "❌"];
    return '<div class="status-banner banner-' + cfg[0] + '">' +
      '<div class="sb-title">' + cfg[1] + " " + escHtml(title) + "</div>" +
      (detail ? '<div class="sb-detail">' + detail + "</div>" : "") +
      "</div>";
  }

  // 把横幅插到 host 顶部（同一 host 只保留最新一条），可选滚动到可见
  function showBanner(host, kind, title, detail, scroll) {
    if (!host) return;
    host.insertAdjacentHTML("afterbegin", statusBanner(kind, title, detail));
    const latest = host.firstElementChild;
    host.querySelectorAll(".status-banner").forEach((b) => { if (b !== latest) b.remove(); });
    if (scroll) host.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }

  // ---------- 遮罩层 / 最小化悬浮进度 ----------
  // miniState：悬浮条要展示的内容（标题 / 百分比 / 详细消息）
  let miniState = { label: "处理中…", pct: 0, msg: "" };

  function refreshMini() {
    if (el.miniProgress.style.display === "none") return;
    el.miniTitle.textContent = miniState.label + (miniState.msg ? " · " + miniState.msg : "");
    el.miniPct.textContent = miniState.pct + "%";
    el.miniBar.style.width = miniState.pct + "%";
    el.miniProgress.title = (miniState.msg || miniState.label) + "（点击展开）";
  }
  function hideMini() { el.miniProgress.style.display = "none"; }
  function showMini() {
    el.miniProgress.style.display = "flex";
    refreshMini();
  }

  function showOverlay(title) {
    miniState = { label: title || "处理中…", pct: 0, msg: "" };
    el.ovTitle.textContent = miniState.label;
    el.ovSub.textContent = "";
    setBar(el.ovBar, 0);
    el.overlay.style.display = "flex";
    hideMini();
  }

  // 完全关闭（任务结束 / 请求完成 / 出错）：大弹窗与悬浮条一并消失
  function hideOverlay() {
    el.overlay.style.display = "none";
    hideMini();
  }

  // 收起为右上角悬浮条（后台任务继续跑，进度实时同步）
  function minimizeOverlay() {
    el.overlay.style.display = "none";
    refreshMini();
    showMini();
  }

  function setBar(bar, pct) {
    if (!bar) return;
    bar.style.width = pct + "%";
    bar.textContent = pct + "%";
  }

  // 把进度同步到所有（可见或隐藏的）进度条 + 悬浮条，保证任意阶段刷新不丢失
  function syncAllBars(pct, msg) {
    const text = pct + "%" + (msg ? " " + msg : "");
    [el.progressBar, el.upBar, el.histBar, el.ovBar].forEach((b) => {
      if (!b) return;
      b.style.width = pct + "%";
      b.textContent = text;
    });
    el.ovSub.textContent = msg || "";
    miniState.pct = pct;
    miniState.msg = msg || "";
    refreshMini();
  }

  // 点击悬浮条 → 展开完整进度弹窗（保留当前标题/消息/进度）
  el.miniProgress.addEventListener("click", () => {
    hideMini();
    el.ovTitle.textContent = miniState.label;
    el.ovSub.textContent = miniState.msg;
    setBar(el.ovBar, miniState.pct);
    el.overlay.style.display = "flex";
  });

  // ---------- 任务轮询（构建 / 上传 / 历史上传共用） ----------
  // opts: { btn, onProgress(pct,msg), onDone(s), onError(msg) }
  function pollJob(jobId, opts) {
    const timer = setInterval(async () => {
      let s;
      try { s = await (await fetch("/api/status/" + jobId)).json(); }
      catch { return; } // 后续轮询会重试
      const pct = s.percent || 0;
      if (opts.onProgress) opts.onProgress(pct, s.message || "");
      if (s.state === "done" || s.state === "error") {
        clearInterval(timer);
        hideOverlay();
        if (opts.btn) opts.btn.disabled = false;
        if (s.state === "error") {
          const msg = s.error || "未知错误";
          if (opts.onError) opts.onError(msg);
          else alert("出错了：" + msg);
          return;
        }
        opts.onDone && opts.onDone(s);
      }
    }, 800);
  }

  // ============================================================
  // ① 扫描 / 选择文件夹
  // ============================================================
  // 选择文件夹 → 两段进度：
  //   阶段① 浏览器→本服务的本地传输（xhr.upload 字节进度）
  //   阶段② 后端识别格式 + 生成预览（job 轮询，真实 X/N 逐文件进度）
  el.dirPicker.addEventListener("change", function () {
    const files = Array.from(this.files || []).filter((f) => /\.(png|jpe?g|gif|webp|bmp)$/i.test(f.name));
    this.value = "";
    if (!files.length) return showScanError("选中的文件夹里没有图片文件");
    showScanError("");
    showOverlay("读取文件夹…（" + files.length + " 个文件）");

    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/scan_upload");
    xhr.upload.onprogress = (e) => {
      if (!e.lengthComputable || el.overlay.style.display !== "flex") return;
      syncAllBars(
        Math.round((e.loaded / e.total) * 100),
        "正在传输 " + files.length + " 个文件…"
      );
    };
    xhr.onload = () => {
      let d;
      try { d = JSON.parse(xhr.responseText); }
      catch { hideOverlay(); return showScanError("解析响应失败"); }
      if (xhr.status !== 200) { hideOverlay(); return showScanError(d.error || "读取失败"); }
      if (!d.job_id) { hideOverlay(); return showScanError("服务端未返回识别任务"); }

      // 阶段②：后台识别 + 预览，轮询真实逐文件进度
      pollJob(d.job_id, {
        onProgress: (pct, msg) => syncAllBars(pct, msg),
        onDone(s) {
          const items = (s.results && s.results.items) || [];
          if (!items.length) { showScanError("文件夹里没有可用的图片文件"); return; }
          applyItems(items);
        },
        onError(msg) { showScanError("读取失败：" + msg); },
      });
    };
    xhr.onerror = () => { hideOverlay(); showScanError("上传失败：无法连接服务"); };
    xhr.send(fd);
  });

  $("scanBtn").addEventListener("click", async () => {
    const folder = el.folder.value.trim().replace(/^["']|["']$/g, "");
    showScanError("");
    if (!folder) return showScanError("请输入文件夹路径，或用「选择文件夹…」按钮");
    showOverlay("扫描文件夹…");
    try {
      const d = await jsonPost("/api/scan", { folder });
      hideOverlay();
      if (!d.items || !d.items.length) return showScanError("该文件夹里没有可用的图片文件");
      applyItems(d.items);
    } catch (e) {
      hideOverlay();
      showScanError("无法连接服务：" + e.message + "（请确认 start.bat 的黑窗口还开着）");
    }
  });

  function applyItems(items) {
    ITEMS = items;
    SELECTED = new Set(items.map((i) => i.id));
    el.stickerCard.style.display = "";
    el.buildCard.style.display = "";
    el.guideCard.style.display = "";
    el.uploadCard.style.display = "none"; // 等生成完成后再展示
    el.countInfo.textContent = "共 " + ITEMS.length + " 个";
    renderGrid();
  }

  // ============================================================
  // ② 勾选表情
  // ============================================================
  el.filter.addEventListener("input", renderGrid);
  $("selectAllBtn").addEventListener("click", () => selectAll(true));
  $("selectNoneBtn").addEventListener("click", () => selectAll(false));

  function renderGrid() {
    const filter = el.filter.value.trim().toLowerCase();
    el.grid.innerHTML = "";
    for (const it of ITEMS) {
      if (filter && !it.name.toLowerCase().includes(filter)) continue;
      const div = document.createElement("div");
      div.className = "sticker" + (SELECTED.has(it.id) ? " sel" : "");
      div.innerHTML =
        '<span class="check">✓</span>' +
        '<span class="tag ' + (it.kind === "gif" ? "" : "static") + '">' + (it.kind === "gif" ? "动图" : "静态") + "</span>" +
        '<img src="' + it.preview + '" loading="lazy">' +
        '<div class="name" title="' + it.name.replace(/"/g, "") + '">' + it.name + "</div>";
      div.onclick = () => toggle(it.id);
      div.ondblclick = (e) => {
        e.stopPropagation();
        el.viewerImg.src = it.preview;
        el.viewer.showModal();
      };
      el.grid.appendChild(div);
    }
    el.selCount.textContent = SELECTED.size;
  }

  function toggle(id) {
    SELECTED.has(id) ? SELECTED.delete(id) : SELECTED.add(id);
    renderGrid();
  }
  function selectAll(on) {
    SELECTED = on ? new Set(ITEMS.map((i) => i.id)) : new Set();
    renderGrid();
  }

  // ============================================================
  // ③ 生成贴纸包
  // ============================================================
  el.buildBtn.addEventListener("click", async () => {
    const selected = ITEMS.filter((i) => SELECTED.has(i.id));
    if (!selected.length) return alert("请先勾选至少一个表情");
    el.buildBtn.disabled = true;
    el.result.style.display = "none";
    el.failList.textContent = "";
    el.progress.style.display = "";
    el.uploadCard.style.display = "none";
    showOverlay("生成贴纸中…");
    try {
      const d = await jsonPost("/api/build", {
        items: selected,
        pack_name: el.packName.value,
      });
      buildJobId = d.job_id;
      pollJob(d.job_id, {
        btn: el.buildBtn,
        onProgress: (pct, msg) => syncAllBars(pct, msg),
        onDone(s) {
          el.progressBar.style.width = "100%";
          el.progressBar.textContent = "100%";
          el.result.style.display = "block"; // 注意不能用 ""：CSS #result{display:none} 会兜底隐藏
          const res = s.results || {};
          lastRes = res;
          const fails = res.failures || [];
          const stat = "静态 " + (res.static_count || 0) + " 个 · 动图 " + (res.anim_count || 0) + " 个";
          if (fails.length) {
            // 部分失败：警示横幅 + 明细列表（保留在 failList）
            showBanner(el.result, "warn", "生成完成，但 " + fails.length + " 个文件转换失败", "", true);
            el.failList.textContent = "失败项：" + fails.map((f) => f.name + "：" + f.error).join("\n");
          } else {
            showBanner(el.result, "ok", "生成成功：" + stat, "", true);
            el.failList.textContent = "";
          }
          el.resultStats.style.display = "none"; // 统计已并入横幅，隐藏旧文本
          el.dlBtn.dataset.job = d.job_id;
          // 生成后可选择包上传
          el.uploadCard.style.display = "";
          renderPackSelect(el.packSelect, selPacks, res.static_count || 0, res.anim_count || 0);
        },
        onError(msg) {
          // 生成失败：红色横幅显示错误，替代原来的 alert
          el.result.style.display = "block"; // 同上：显式 block，绕开 CSS #result{display:none}
          showBanner(el.result, "err", "生成失败", escHtml(msg), true);
        },
      });
    } catch (e) {
      el.buildBtn.disabled = false;
      hideOverlay();
      alert(e.message);
    }
  });

  el.dlBtn.addEventListener("click", () => {
    if (buildJobId) window.location.href = "/api/download/" + buildJobId;
  });

  // ============================================================
  // ④ 全自动上传
  // ============================================================
  el.upBtn.addEventListener("click", async () => {
    if (!buildJobId) return alert("请先完成第③步生成");
    el.upBtn.disabled = true;
    el.upResult.textContent = "";
    el.upProgress.style.display = "";
    showOverlay("上传到 Telegram…");
    try {
      // 以用户当前勾选为准（DOM 实时读取），并回写内存状态保持一致
      selPacks = readPacks(el.packSelect);
      // token 与用户 ID 已从环境变量读取，前端不再采集
      const d = await jsonPost("/api/upload", {
        job_id: buildJobId,
        title: el.upTitle.value,
        static_name: el.staticName.value,
        anim_name: el.animName.value,
        static_packs: toArray(selPacks.static),
        anim_packs: toArray(selPacks.anim),
      });
      pollJob(d.job_id, {
        btn: el.upBtn,
        onProgress: (pct, msg) => syncAllBars(pct, msg),
        onDone(s) {
          el.upResult.innerHTML = renderUploadSuccess(s);
          el.upResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
        },
        onError(msg) {
          // 失败：红色横幅 + 错误详情，自动滚动到可见（替代原来的一行小字）
          el.upResult.innerHTML = "";
          showBanner(el.upResult, "err", "上传失败", escHtml(msg), true);
        },
      });
    } catch (e) {
      el.upBtn.disabled = false;
      hideOverlay();
      alert(e.message);
    }
  });

  // 把 Set 转为升序数组；空集 → []（后端据此跳过该类型）
  function toArray(set) { return [...set].sort((a, b) => a - b); }

  // 实时从 DOM 读取当前勾选的分包（以用户看到的勾选为准，避免状态不同步导致误传全量）
  // 返回 { static: Set<包号>, anim: Set<包号> }
  function readPacks(container) {
    const res = { static: new Set(), anim: new Set() };
    if (!container) return res;
    container.querySelectorAll("input[type=checkbox]").forEach((cb) => {
      if (cb.checked) res[cb.dataset.type].add(+cb.dataset.n);
    });
    return res;
  }

  // 依据给定来源的分包数量，把可上传的分包（每 ≤120 张拆第1包/第2包…）渲染进指定容器，
  // 勾选状态写入对应的 sel 对象（卡④用 selPacks，弹窗用 selPacksHist）。
  function renderPackSelect(container, sel, staticCount, animCount) {
    const groups = [
      { key: "static", label: "静态包", count: staticCount || 0 },
      { key: "anim", label: "动图包", count: animCount || 0 },
    ];
    sel.static = new Set(); sel.anim = new Set();
    let html = "";
    for (const g of groups) {
      if (!g.count) continue;
      const packs = Math.ceil(g.count / 120);
      html += '<div class="pack-group"><div class="pack-group-title">' + g.label +
        "（共 " + g.count + " 张，拆 " + packs + " 包）</div><div class='pack-list'>";
      for (let n = 1; n <= packs; n++) {
        const from = (n - 1) * 120 + 1;
        const to = Math.min(n * 120, g.count);
        sel[g.key].add(n); // 默认全选
        html += "<label class='pack-opt'><input type='checkbox' data-type='" + g.key + "' data-n='" + n +
          "' checked> 第" + n + "包（第" + from + "–" + to + "张）</label>";
      }
      html += "</div></div>";
    }
    container.innerHTML = html;
    container.style.display = html ? "block" : "none";
    container.querySelectorAll("input[type=checkbox]").forEach((cb) => {
      cb.addEventListener("change", () => {
        const key = cb.dataset.type;
        const n = +cb.dataset.n;
        if (cb.checked) sel[key].add(n); else sel[key].delete(n);
      });
    });
  }

  // ============================================================
  // 📦 历史包上传
  // ============================================================
  // 载入历史包列表：有则显示「从历史包选择上传」按钮，并填充弹窗下拉
  (async function loadHistory() {
    try {
      const d = await (await fetch("/api/history")).json();
      historyItems = d.items || [];
      if (historyItems.length) {
        historyItems.forEach((h) => {
          const o = document.createElement("option");
          o.value = h.id;
          o.textContent = "历史包 " + h.time + "（静态 " + h.static + "，动图 " + h.anim + "）";
          el.histSelect.appendChild(o);
        });
        el.histCard.style.display = "";   // 有历史包才显示按钮
      }
    } catch { /* 忽略历史包加载失败 */ }
  })();

  // 打开历史包上传弹窗
  el.histOpenBtn.addEventListener("click", () => {
    el.histResult.innerHTML = "";
    el.histProgress.style.display = "none";
    if (historyItems.length) {
      el.histSelect.value = historyItems[0].id;
      renderPackSelect(el.histPackSelect, selPacksHist, historyItems[0].static, historyItems[0].anim);
    }
    el.histModal.showModal();
  });

  // 弹窗内切换历史包 → 重新渲染分包
  el.histSelect.addEventListener("change", () => {
    const item = historyItems.find((h) => h.id === el.histSelect.value);
    if (item) renderPackSelect(el.histPackSelect, selPacksHist, item.static, item.anim);
  });

  // 关闭弹窗
  el.histClose.addEventListener("click", () => el.histModal.close());
  el.histModal.addEventListener("click", (e) => { if (e.target === el.histModal) el.histModal.close(); });

  // 弹窗：从历史包上传（与卡④共用 pollJob；点上传即关弹窗，进度/结果显示在历史卡片）
  el.histUpBtn.addEventListener("click", async () => {
    const hid = el.histSelect.value;
    if (!hid) return alert("请先选择一个历史包");

    // 以弹窗内用户勾选为准（DOM 实时读取），随后立即关闭弹窗
    selPacksHist = readPacks(el.histPackSelect);

    el.histUpBtn.disabled = true;
    el.histModal.close();
    el.histResult.innerHTML = "";
    el.histResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
    el.histProgress.style.display = "";
    setBar(el.histBar, 0);
    showOverlay("从历史包上传到 Telegram…");
    try {
      const d = await jsonPost("/api/upload", {
        history_id: hid,
        title: el.histTitle.value,
        static_name: el.histStaticName.value,
        anim_name: el.histAnimName.value,
        static_packs: toArray(selPacksHist.static),
        anim_packs: toArray(selPacksHist.anim),
      });
      pollJob(d.job_id, {
        btn: el.histUpBtn,
        onProgress: (pct, msg) => syncAllBars(pct, msg),
        onDone(s) {
          el.histProgress.style.display = "none";
          el.histResult.innerHTML = renderUploadSuccess(s);
          el.histResult.scrollIntoView({ behavior: "smooth", block: "nearest" });
        },
        onError(msg) {
          el.histProgress.style.display = "none";
          el.histResult.innerHTML = "";
          showBanner(el.histResult, "err", "上传失败", escHtml(msg), true);
        },
      });
    } catch (e) {
      el.histUpBtn.disabled = false;
      hideOverlay();
      el.histProgress.style.display = "none";
      alert(e.message);
    }
  });

  function renderUploadSuccess(s) {
    const created = (s.results && s.results.created) || [];
    const ok = created.length > 0;
    const summary = ok
      ? "共创建 " + created.length + " 个贴纸包（静态 + 动图）"
      : "没有创建任何贴纸包（请检查是否勾选了要上传的包）";
    let html = statusBanner(ok ? "ok" : "warn", ok ? "上传成功" : "上传完成", summary);
    html +=
      '<div class="success-guide">' +
      '<div class="sg-title">按下面两步开始使用：</div>' +
      '<div class="sg-step"><b>第 1 步：添加贴纸包</b>——推荐做法：把下面的链接<b>作为消息发送到 Telegram 任意聊天</b>' +
      '（如"收藏夹"/Saved Messages），然后在 Telegram 应用内点开该链接，点「添加贴纸」即可。' +
      '<div class="sg-note">⚠️ 不建议直接在浏览器里打开链接：网页上的 "Add Stickers" 按钮只是尝试唤起 Telegram 客户端，' +
      '电脑上没装桌面版或浏览器拦截了协议时点击会无反应。手机浏览器打开则会正常跳转到 App。</div></div>' +
      '<div class="sg-links">' +
      created.map((n) => '<a href="https://t.me/addstickers/' + n + '" target="_blank">t.me/addstickers/' + n + "</a>").join("<br>") +
      "</div></div>";
    if (created.length > 1) {
      html += '<div class="sg-note">💡 贴纸超过 120 张会自动拆成多个包，上面每个链接都要点一次添加。</div>';
    }
    html +=
      '<div class="sg-step"><b>第 2 步：分享给朋友</b>——直接把上面的链接发给任何人，对方点开即可添加同款贴纸。</div>' +
      '<div class="sg-note">📌 无需发布：通过 Bot API 创建的贴纸包即建即用（与 @Stickers 的 /publish 是两套机制），' +
      "但不会自动出现在贴纸面板，需通过上面的链接添加一次。" +
      "在 Telegram 任意聊天的表情面板里就能找到它们。" +
      '以后想追加表情，用本工具重新生成后可把新包建成 _2 之类的名字，或用 @Stickers 的 /addsticker。</div></div>';
    return html;
  }

  // 遮罩「收起」按钮 → 最小化为右上角悬浮条
  const cancelBtn = document.querySelector(".cancel");
  if (cancelBtn) cancelBtn.addEventListener("click", minimizeOverlay);

  // ============================================================
  // 环境变量预设提示
  // ============================================================
  (async function loadPreset() {
    try {
      const p = await (await fetch("/api/preset")).json();
      let txt = "";
      if (p.has_token && p.owner_id) {
        txt = "✓ 已从环境变量读取 TG_BOT_TOKEN 与 TG_OWNER_ID，无需再填写。";
      } else {
        const missing = [p.has_token ? "" : "TG_BOT_TOKEN", p.owner_id ? "" : "TG_OWNER_ID"].filter(Boolean);
        txt = "⚠️ 未配置：" + missing.join("、") + "（请在 start.bat 中设置后再上传）";
      }
      if (p.bot_name) txt += " 机器人 @" + p.bot_name + "，包名将自动以 _by_" + (p.bot_name || "机器人名") + " 结尾。";
      el.envInfo.style.display = "block";
      el.envInfo.textContent = txt;
    } catch { /* 忽略预设加载失败 */ }
  })();
})();
