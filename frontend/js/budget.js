/* 预算监控面板：预算管理 + 偏差列表/汇总/监控状态。 */
const BudgetPanel = (() => {
  const LEVEL_TAG = { low: "tag-low", medium: "tag-medium", high: "tag-high" };
  const UNIFORM_CURVE = Array(12).fill(1 / 12);

  async function loadBase() {
    const [depts, projects, cats] = await Promise.all([
      API.get("/departments"), API.get("/projects"), API.get("/cost-categories"),
    ]);
    return { depts, projects, cats };
  }

  async function render() {
    const base = await loadBase();
    const content = document.getElementById("content");
    const canManage = Auth.hasPerm("budget:manage");
    content.innerHTML = `
      <div class="panel">
        <div class="flex-between">
          <h3>预算列表</h3>
          ${canManage ? `<button id="budget-new-btn" class="btn btn-primary btn-sm">新建年度预算</button>` : ""}
        </div>
        <div id="budget-list" class="mt"></div>
      </div>
      <div class="panel">
        <h3>偏差明细</h3>
        <div class="filters">
          <select id="f-dept"><option value="">全部部门</option>${base.depts.map((d) => `<option value="${d.id}">${d.name}</option>`).join("")}</select>
          <select id="f-proj"><option value="">全部项目</option>${base.projects.map((p) => `<option value="${p.id}">${p.name}</option>`).join("")}</select>
          <select id="f-cat"><option value="">全部科目</option>${base.cats.map((c) => `<option value="${c.id}">${c.name}</option>`).join("")}</select>
          <select id="f-level"><option value="">全部等级</option><option value="low">low</option><option value="medium">medium</option><option value="high">high</option></select>
          <input id="f-period" placeholder="期间 2026-06" />
          <button id="f-search" class="btn btn-sm">查询</button>
        </div>
        <div id="dev-list"></div>
      </div>
      <div class="panel">
        <h3>偏差汇总（按部门）</h3>
        <div id="summary-box"></div>
      </div>
      <div class="panel">
        <h3>最近监控任务</h3>
        <div id="monitor-status"></div>
      </div>
      <div id="budget-form-box"></div>
    `;
    loadBudgets();
    loadDeviations();
    loadSummary();
    loadMonitorStatus();
    document.getElementById("budget-new-btn") && document.getElementById("budget-new-btn")
      .addEventListener("click", () => showBudgetForm(base));
    document.getElementById("f-search").addEventListener("click", () => loadDeviations());
    document.getElementById("f-period").addEventListener("keydown", (e) => e.key === "Enter" && loadDeviations());
  }

  async function loadBudgets() {
    const data = await API.get("/budgets");
    const base = await loadBase();
    const el = document.getElementById("budget-list");
    if (!data.items.length) { el.innerHTML = '<p class="muted">暂无预算</p>'; return; }
    el.innerHTML = `<table>
      <thead><tr><th>部门</th><th>项目</th><th>科目</th><th>年度</th><th>金额</th><th>分摊曲线</th><th></th></tr></thead>
      <tbody>${data.items.map((b) => `
        <tr>
          <td>${nameOf(base.depts, b.department_id)}</td><td>${nameOf(base.projects, b.project_id)}</td>
          <td>${nameOf(base.cats, b.cost_category_id)}</td><td>${b.budget_year}</td><td>¥${b.amount}</td>
          <td><div class="flex" style="min-width:120px">${curveBars(b.allocation_curve)}</div></td>
          <td>${Auth.hasPerm("budget:manage") ? `<button class="btn btn-sm" data-adjust="${b.id}">调整</button>` : ""}</td>
        </tr>`).join("")}</tbody></table>`;
    el.querySelectorAll("[data-adjust]").forEach((btn) =>
      btn.addEventListener("click", () => showBudgetForm(base, data.items.find((b) => b.id === Number(btn.dataset.adjust))))
    );
  }

  function nameOf(list, id) {
    const hit = list.find((x) => x.id === id);
    return hit ? hit.name : String(id);
  }

  function curveBars(curve) {
    if (!curve) return '<span class="muted">—</span>';
    return curve.map((v) => `<div class="bar"><i style="width:${Math.round(v * 100)}%"></i></div>`).join("");
  }

  async function loadDeviations() {
    const p = new URLSearchParams();
    ["f-dept", "f-proj", "f-cat", "f-level"].forEach((id) => {
      const v = document.getElementById(id).value;
      if (v) p.set(id.slice(2).replace("dept", "department_id").replace("proj", "project_id").replace("cat", "cost_category_id").replace("level", "level"), v);
    });
    const period = document.getElementById("f-period").value.trim();
    if (period) { p.set("period_from", period); p.set("period_to", period); }
    const data = await API.get("/deviations?" + p.toString());
    const el = document.getElementById("dev-list");
    if (!data.items.length) { el.innerHTML = '<p class="muted">暂无偏差（执行监控任务后生成）</p>'; return; }
    el.innerHTML = `<table>
      <thead><tr><th>部门</th><th>项目</th><th>科目</th><th>期间</th><th>预算</th><th>实际</th><th>偏差</th><th>比例</th><th>等级</th><th>责任人</th><th>触发原因</th></tr></thead>
      <tbody>${data.items.map((d) => `
        <tr>
          <td>${d.department_name}</td><td>${d.project_name}</td><td>${d.cost_category_name}</td><td>${d.period}</td>
          <td>¥${d.budget_amount}</td><td>¥${d.actual_amount}</td>
          <td class="${Number(d.deviation_amount) >= 0 ? "text-danger" : "text-ok"}">¥${d.deviation_amount}</td>
          <td>${(Number(d.deviation_ratio) * 100).toFixed(2)}%</td>
          <td><span class="tag ${LEVEL_TAG[d.level]}">${d.level}</span></td>
          <td>${d.owner || "—"}</td><td>${d.trigger_reason || "—"}</td>
        </tr>`).join("")}</tbody></table>`;
  }

  async function loadSummary() {
    const data = await API.get("/deviations/summary?group_by=department");
    const el = document.getElementById("summary-box");
    if (!data.length) { el.innerHTML = '<p class="muted">暂无汇总数据</p>'; return; }
    el.innerHTML = `<table>
      <thead><tr><th>部门</th><th>预算合计</th><th>实际合计</th><th>偏差</th><th>比例</th><th>等级</th></tr></thead>
      <tbody>${data.map((g) => `
        <tr><td>${g.name}</td><td>¥${g.budget_total}</td><td>¥${g.actual_total}</td>
        <td>¥${g.deviation_amount}</td><td>${(Number(g.deviation_ratio) * 100).toFixed(2)}%</td>
        <td><span class="tag ${LEVEL_TAG[g.level]}">${g.level}</span></td></tr>`).join("")}</tbody></table>`;
  }

  async function loadMonitorStatus() {
    const el = document.getElementById("monitor-status");
    try {
      const s = await API.get("/monitor/status");
      el.innerHTML = s.last_run_at
        ? `最近执行：${s.last_run_at.replace("T", " ").slice(0, 16)}　状态：<b>${s.status}</b>　偏差数：${s.snapshot ? s.snapshot.deviation_count : "-"}（期间 ${s.snapshot ? s.snapshot.period : "-"}）`
        : '<span class="muted">尚未执行监控任务</span>';
    } catch (e) { el.innerHTML = '<span class="muted">获取监控状态失败</span>'; }
  }

  function showBudgetForm(base, budget) {
    const box = document.getElementById("budget-form-box");
    const b = budget || {};
    box.innerHTML = `
      <div class="panel">
        <h3>${budget ? "调整预算 #" + budget.id : "新建年度预算"}</h3>
        <div class="form-grid">
          <div class="form-item"><label>部门</label><select id="bf-dept" ${budget ? "disabled" : ""}>${base.depts.map((d) => `<option value="${d.id}" ${d.id === b.department_id ? "selected" : ""}>${d.name}</option>`).join("")}</select></div>
          <div class="form-item"><label>项目</label><select id="bf-proj" ${budget ? "disabled" : ""}>${base.projects.map((p) => `<option value="${p.id}" ${p.id === b.project_id ? "selected" : ""}>${p.name}</option>`).join("")}</select></div>
          <div class="form-item"><label>科目</label><select id="bf-cat" ${budget ? "disabled" : ""}>${base.cats.map((c) => `<option value="${c.id}" ${c.id === b.cost_category_id ? "selected" : ""}>${c.name}</option>`).join("")}</select></div>
          <div class="form-item"><label>年度</label><input id="bf-year" value="${b.budget_year || new Date().getFullYear()}" ${budget ? "disabled" : ""} /></div>
          <div class="form-item"><label>金额（元）</label><input id="bf-amount" type="number" step="0.01" value="${b.amount || 100000}" /></div>
          <div class="form-item"><label>调整原因（调整时）</label><input id="bf-reason" placeholder="可选" /></div>
        </div>
        <h4>12 个月分摊曲线（合计应为 1）</h4>
        <div class="form-grid" id="bf-curve-grid">
          ${Array.from({ length: 12 }, (_, i) => `
            <div class="form-item"><label>${i + 1} 月</label>
            <input type="number" step="0.01" data-curve="${i}" value="${b.allocation_curve ? b.allocation_curve[i] : UNIFORM_CURVE[i].toFixed(6)}" /></div>`).join("")}
        </div>
        <div id="bf-curve-sum" class="muted"></div>
        <div class="form-actions">
          <button id="bf-save" class="btn btn-primary">${budget ? "保存调整" : "创建"}</button>
          <button id="bf-cancel" class="btn">取消</button>
        </div>
      </div>`;
    updateCurveSum();
    document.getElementById("bf-curve-grid").addEventListener("input", updateCurveSum);
    document.getElementById("bf-save").addEventListener("click", () => saveBudget(budget));
    document.getElementById("bf-cancel").addEventListener("click", () => (box.innerHTML = ""));
  }

  function updateCurveSum() {
    const inputs = document.querySelectorAll("[data-curve]");
    const sum = [...inputs].reduce((acc, inp) => acc + (Number(inp.value) || 0), 0);
    const el = document.getElementById("bf-curve-sum");
    el.textContent = "合计：" + sum.toFixed(4) + (Math.abs(sum - 1) > 0.0001 ? "（需为 1）" : " ✓");
  }

  async function saveBudget(existing) {
    const curve = [...document.querySelectorAll("[data-curve]")].map((inp) => Number(inp.value));
    const payload = { allocation_curve: curve };
    if (existing) {
      payload.amount = document.getElementById("bf-amount").value;
      payload.reason = document.getElementById("bf-reason").value || "前端调整";
      await API.put("/budgets/" + existing.id, payload);
      App.toast("预算已调整（留痕）");
    } else {
      Object.assign(payload, {
        department_id: Number(document.getElementById("bf-dept").value),
        project_id: Number(document.getElementById("bf-proj").value),
        cost_category_id: Number(document.getElementById("bf-cat").value),
        budget_year: document.getElementById("bf-year").value.trim(),
        amount: document.getElementById("bf-amount").value,
      });
      await API.post("/budgets", payload);
      App.toast("预算已创建");
    }
    render();
  }

  return { render };
})();
