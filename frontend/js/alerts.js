/* 预警中心：budget/ar 两类预警统一展示，支持过滤与标记已读。 */
const Alerts = (() => {
  const LEVEL_TAG = { info: "tag-info", warning: "tag-warning", critical: "tag-critical" };
  const TYPE_LABEL = { budget: "预算", ar: "应收" };

  async function render() {
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="panel">
        <h3>预警中心</h3>
        <div class="filters">
          <select id="al-type"><option value="">全部类型</option><option value="budget">预算</option><option value="ar">应收</option></select>
          <select id="al-level"><option value="">全部等级</option><option value="info">info</option><option value="warning">warning</option><option value="critical">critical</option></select>
          <select id="al-read"><option value="">全部已读状态</option><option value="false">未读</option><option value="true">已读</option></select>
          <button id="al-search" class="btn btn-sm">查询</button>
        </div>
        <div id="al-list"></div>
      </div>
      <div id="al-detail-box"></div>
    `;
    document.getElementById("al-search").addEventListener("click", () => load());
    load();
  }

  async function load() {
    const p = new URLSearchParams();
    const type = document.getElementById("al-type").value;
    const level = document.getElementById("al-level").value;
    const read = document.getElementById("al-read").value;
    if (type) p.set("alert_type", type);
    if (level) p.set("level", level);
    if (read !== "") p.set("read", read);
    const data = await API.get("/alerts?" + p.toString());
    const el = document.getElementById("al-list");
    if (!data.items.length) { el.innerHTML = '<p class="muted">暂无预警</p>'; return; }
    el.dataset.items = JSON.stringify(data.items);
    el.innerHTML = `<table>
      <thead><tr><th>类型</th><th>等级</th><th>摘要</th><th>时间</th><th>状态</th><th></th></tr></thead>
      <tbody>${data.items.map((a) => `
        <tr>
          <td>${TYPE_LABEL[a.alert_type] || a.alert_type}</td>
          <td><span class="tag ${LEVEL_TAG[a.level] || ""}">${a.level}</span></td>
          <td>${a.summary}</td>
          <td>${(a.created_at || "").replace("T", " ").slice(0, 16)}</td>
          <td>${a.read ? '<span class="tag tag-settled">已读</span>' : '<span class="tag tag-warning">未读</span>'}</td>
          <td>
            <button class="btn btn-sm" data-show="${a.id}">详情</button>
            ${a.read ? "" : `<button class="btn btn-sm btn-primary" data-read="${a.id}">标记已读</button>`}
          </td>
        </tr>`).join("")}</tbody></table>`;
    el.querySelectorAll("[data-read]").forEach((b) =>
      b.addEventListener("click", async () => {
        await API.post(`/alerts/${b.dataset.read}/read`);
        App.toast("已标记已读"); load();
      })
    );
    el.querySelectorAll("[data-show]").forEach((b) =>
      b.addEventListener("click", () => showDetail(b.dataset.show))
    );
  }

  function showDetail(id) {
    const el = document.getElementById("al-list");
    const items = JSON.parse(el.dataset.items || "[]");
    const alert = items.find((x) => String(x.id) === String(id));
    if (!alert) return;
    const box = document.getElementById("al-detail-box");
    box.innerHTML = `
      <div class="panel">
        <h3>预警详情 #${id}</h3>
        <p>摘要：${alert.summary}</p>
        <h4>detail（JSON）</h4>
        <pre class="muted" style="white-space:pre-wrap;word-break:break-all">${JSON.stringify(alert.detail || {}, null, 2)}</pre>
        <button id="al-detail-close" class="btn btn-sm">关闭</button>
      </div>`;
    document.getElementById("al-detail-close").addEventListener("click", () => (box.innerHTML = ""));
  }

  return { render };
})();
