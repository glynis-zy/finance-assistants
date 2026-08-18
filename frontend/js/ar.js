/* 应收预警面板：应收列表 / 新增 / 回款 / 催收 / 风险排名 / 客户详情 / 任务状态。 */
const ArPanel = (() => {
  const LEVEL_TAG = { low: "tag-low", medium: "tag-medium", high: "tag-high" };
  const STATUS_TAG = { open: "tag-open", partial: "tag-partial", settled: "tag-settled" };

  async function loadBase() {
    const [customers, contracts] = await Promise.all([
      API.get("/customers"), API.get("/contracts"),
    ]);
    return { customers, contracts };
  }

  async function render() {
    const base = await loadBase();
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="panel">
        <h3>风险排名（默认 high ≥ 70）</h3>
        <div id="risk-ranking"></div>
      </div>
      <div class="panel">
        <div class="flex-between">
          <h3>应收列表</h3>
          <button id="ar-new-btn" class="btn btn-primary btn-sm">新增应收</button>
        </div>
        <div id="ar-list" class="mt"></div>
      </div>
      <div class="panel">
        <h3>登记回款</h3>
        <div class="form-grid">
          <div class="form-item"><label>应收单 ID</label><input id="pay-rec" type="number" /></div>
          <div class="form-item"><label>客户</label><select id="pay-customer">${base.customers.map((c) => `<option value="${c.id}">${c.name}</option>`).join("")}</select></div>
          <div class="form-item"><label>金额（元）</label><input id="pay-amount" type="number" step="0.01" /></div>
        </div>
        <div class="form-actions"><button id="pay-btn" class="btn btn-primary">登记回款</button></div>
      </div>
      <div class="panel">
        <h3>登记催收</h3>
        <div class="form-grid">
          <div class="form-item"><label>客户</label><select id="col-customer">${base.customers.map((c) => `<option value="${c.id}">${c.name}</option>`).join("")}</select></div>
          <div class="form-item"><label>渠道</label><input id="col-channel" value="电话" /></div>
          <div class="form-item"><label>结果</label><input id="col-result" value="承诺回款" /></div>
        </div>
        <div class="form-actions"><button id="col-btn" class="btn btn-primary">登记催收（触发重评分）</button></div>
      </div>
      <div class="panel">
        <h3>最近评分任务</h3>
        <div id="ar-risk-status"></div>
      </div>
      <div id="ar-form-box"></div>
      <div id="ar-detail-box"></div>
    `;
    loadRanking();
    loadList();
    loadRiskStatus();
    document.getElementById("ar-new-btn").addEventListener("click", () => showReceivableForm(base));
    document.getElementById("pay-btn").addEventListener("click", createPayment);
    document.getElementById("col-btn").addEventListener("click", createCollection);
  }

  async function loadRanking() {
    const el = document.getElementById("risk-ranking");
    try {
      const data = await API.get("/ar/risk-ranking");
      if (!data.length) { el.innerHTML = '<p class="muted">暂无高风险客户（执行评分任务后生成）</p>'; return; }
      el.innerHTML = `<table>
        <thead><tr><th>客户</th><th>风险分</th><th>等级</th><th>逾期金额</th><th>预计回款</th><th>预计逾期</th><th>催收优先级</th><th></th></tr></thead>
        <tbody>${data.map((r) => `
          <tr>
            <td>${r.customer_name}</td><td><b>${r.risk_score}</b></td>
            <td><span class="tag ${LEVEL_TAG[r.risk_level]}">${r.risk_level}</span></td>
            <td>¥${r.overdue_amount || "0.00"}</td>
            <td>${r.expected_payment_date || "—"}</td><td>${r.expected_overdue_days ?? "—"}</td>
            <td>${r.collection_priority}</td>
            <td><button class="btn btn-sm" data-detail="${r.customer_id}">风险详情</button></td>
          </tr>`).join("")}</tbody></table>`;
      el.querySelectorAll("[data-detail]").forEach((b) =>
        b.addEventListener("click", () => showDetail(Number(b.dataset.detail)))
      );
    } catch (e) { el.innerHTML = `<span class="text-danger">${e.message}</span>`; }
  }

  async function loadList() {
    const data = await API.get("/ar/receivables");
    const el = document.getElementById("ar-list");
    if (!data.items.length) { el.innerHTML = '<p class="muted">暂无应收</p>'; return; }
    el.innerHTML = `<table>
      <thead><tr><th>ID</th><th>客户</th><th>合同</th><th>金额</th><th>未结余额</th><th>到期日</th><th>逾期天数</th><th>状态</th></tr></thead>
      <tbody>${data.items.map((r) => `
        <tr><td>${r.receivable_id}</td><td>${r.customer_name}</td><td>${r.contract_no || "—"}</td>
        <td>¥${r.amount}</td><td>¥${r.outstanding_balance}</td><td>${r.due_date}</td>
        <td class="${r.overdue_days > 0 ? "text-danger" : ""}">${r.overdue_days}</td>
        <td><span class="tag ${STATUS_TAG[r.status] || ""}">${r.status}</span></td></tr>`).join("")}</tbody></table>`;
  }

  async function loadRiskStatus() {
    const el = document.getElementById("ar-risk-status");
    try {
      const s = await API.get("/ar/risk-status");
      el.innerHTML = s.status === "never_run"
        ? '<span class="muted">尚未执行全量评分</span>'
        : `状态：<b>${s.status}</b>　开始：${(s.started_at || "").replace("T", " ").slice(0, 16)}　客户数：${s.customer_count}　高风险：${s.high_risk_count}${s.error ? "　错误：" + s.error : ""}`;
    } catch (e) { el.innerHTML = '<span class="muted">获取评分状态失败</span>'; }
  }

  function showReceivableForm(base) {
    const box = document.getElementById("ar-form-box");
    box.innerHTML = `
      <div class="panel">
        <h3>新增应收</h3>
        <div class="form-grid">
          <div class="form-item"><label>客户</label><select id="rf-customer">${base.customers.map((c) => `<option value="${c.id}">${c.name}</option>`).join("")}</select></div>
          <div class="form-item"><label>合同</label><select id="rf-contract">${base.contracts.map((c) => `<option value="${c.id}">${c.contract_no}</option>`).join("")}</select></div>
          <div class="form-item"><label>金额（元）</label><input id="rf-amount" type="number" step="0.01" value="100000" /></div>
          <div class="form-item"><label>到期日</label><input id="rf-due" type="date" /></div>
        </div>
        <div class="form-actions">
          <button id="rf-save" class="btn btn-primary">创建应收</button>
          <button id="rf-cancel" class="btn">取消</button>
        </div>
      </div>`;
    document.getElementById("rf-due").value = new Date().toISOString().slice(0, 10);
    document.getElementById("rf-save").addEventListener("click", async () => {
      await API.post("/ar/receivables", {
        customer_id: Number(document.getElementById("rf-customer").value),
        contract_id: Number(document.getElementById("rf-contract").value),
        amount: document.getElementById("rf-amount").value,
        due_date: document.getElementById("rf-due").value,
      });
      App.toast("应收已创建（状态 open）");
      render();
    });
    document.getElementById("rf-cancel").addEventListener("click", () => (box.innerHTML = ""));
  }

  async function createPayment() {
    const payload = {
      receivable_id: Number(document.getElementById("pay-rec").value),
      customer_id: Number(document.getElementById("pay-customer").value),
      amount: document.getElementById("pay-amount").value,
    };
    try {
      await API.post("/ar/payments", payload);
      App.toast("回款已登记，状态已重算，风险分已重算");
      render();
    } catch (e) { App.toast(e.message, true); }
  }

  async function createCollection() {
    await API.post("/ar/collection-records", {
      customer_id: Number(document.getElementById("col-customer").value),
      channel: document.getElementById("col-channel").value,
      result: document.getElementById("col-result").value,
    });
    App.toast("催收已登记，风险分已重算");
    render();
  }

  async function showDetail(customerId) {
    const [d, base] = await Promise.all([API.get("/ar/" + customerId + "/detail"), loadBase()]);
    const box = document.getElementById("ar-detail-box");
    const f = (name) => (d.factors && d.factors[name]) || {};
    const factorCard = (name, label) => {
      const x = f(name);
      return `<div class="factor-box">
        <div class="fname">${label}（raw × weight = weighted）</div>
        <div class="fval">${x.raw_score ?? "—"}</div>
        <div class="fmeta">× ${x.weight ?? "—"} = ${x.weighted_score ?? "—"}</div>
        <div class="fmeta muted">${JSON.stringify(x.detail || {})}</div>
      </div>`;
    };
    box.innerHTML = `
      <div class="panel">
        <div class="flex-between">
          <h3>客户风险详情：${d.customer_name}　<span class="tag ${LEVEL_TAG[d.risk_level]}">${d.risk_level}</span></h3>
          <button id="ar-detail-close" class="btn btn-sm">关闭</button>
        </div>
        <div class="kv mt">
          <div><div class="k">总分</div><div class="v">${d.total_score}</div></div>
          <div><div class="k">预计回款日期</div><div class="v">${d.expected_payment_date || "—"}</div></div>
          <div><div class="k">预计逾期天数</div><div class="v">${d.expected_overdue_days ?? "—"}</div></div>
          <div><div class="k">逾期未结金额</div><div class="v">¥${d.overdue_amount || "0.00"}</div></div>
        </div>
        <h4>评分因子</h4>
        <div class="flex" style="flex-wrap:wrap">
          ${factorCard("aging", "账龄因子 ×40%")}
          ${factorCard("term", "账期因子 ×20%")}
          ${factorCard("payment", "历史付款因子 ×30%")}
          ${factorCard("collection", "催收因子 ×10%")}
        </div>
        <h4>当前应收</h4>
        <table><thead><tr><th>应收 ID</th><th>合同</th><th>金额</th><th>未结余额</th><th>到期日</th><th>逾期天数</th><th>状态</th></tr></thead>
        <tbody>${d.receivables.map((r) => `
          <tr><td>${r.receivable_id}</td><td>${r.contract_no || "—"}</td><td>¥${r.amount}</td>
          <td>¥${r.outstanding_balance}</td><td>${r.due_date}</td>
          <td class="${r.overdue_days > 0 ? "text-danger" : ""}">${r.overdue_days}</td>
          <td><span class="tag ${STATUS_TAG[r.status] || ""}">${r.status}</span></td></tr>`).join("")}</tbody></table>
      </div>`;
    document.getElementById("ar-detail-close").addEventListener("click", () => (box.innerHTML = ""));
  }

  return { render };
})();
