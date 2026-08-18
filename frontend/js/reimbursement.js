/* 报销审核面板：列表 / 新建 / 详情 / 附件 / 提交轮询 / 财务复核。 */
const Reimb = (() => {
  const STATUS_TAG = {
    draft: "草稿", pending: "审核中", manual_review: "人工复核", approved: "已通过", returned: "已退回",
  };
  const STATUS_CLASS = { draft: "tag-info", pending: "tag-warning", manual_review: "tag-warning", approved: "tag-settled", returned: "tag-medium" };

  async function loadBase() {
    const [depts, projects, cats] = await Promise.all([
      API.get("/departments"), API.get("/projects"), API.get("/cost-categories"),
    ]);
    return { depts, projects, cats };
  }

  function optionList(items, valueKey, labelFn) {
    return items.map((it) => `<option value="${it[valueKey]}">${labelFn(it)}</option>`).join("");
  }

  async function render() {
    const content = document.getElementById("content");
    const { depts, projects, cats } = await loadBase();
    const isFinance = Auth.hasRole("finance");
    content.innerHTML = `
      <div class="panel">
        <div class="flex-between">
          <h3>报销单列表</h3>
          <div class="flex">
            <select id="reimb-status-filter">
              <option value="">全部状态</option>
              ${Object.entries(STATUS_TAG).map(([k, v]) => `<option value="${k}">${v}</option>`).join("")}
            </select>
            ${isFinance ? `<span class="muted">财务视图：全部单据</span>` : `<span class="muted">我的单据</span>`}
          </div>
        </div>
        <div id="reimb-list" class="mt"></div>
      </div>
      <div class="panel">
        <h3>新建报销单</h3>
        <div class="form-grid">
          <div class="form-item"><label>部门</label><select id="new-dept">${optionList(depts, "id", (d) => d.name)}</select></div>
          <div class="form-item"><label>项目</label><select id="new-project"><option value="">（可选）</option>${optionList(projects, "id", (p) => p.name)}</select></div>
          <div class="form-item"><label>科目</label><select id="new-cat">${optionList(cats, "id", (c) => c.name)}</select></div>
          <div class="form-item"><label>金额（元）</label><input id="new-amount" type="number" step="0.01" value="1000.00" /></div>
          <div class="form-item"><label>发票号</label><input id="new-invoice" placeholder="INV-000001" value="INV-000001" /></div>
          <div class="form-item"><label>说明</label><input id="new-desc" value="差旅费-高铁票" /></div>
        </div>
        <div class="form-actions"><button id="reimb-create-btn" class="btn btn-primary">创建报销单</button></div>
      </div>
    `;
    document.getElementById("reimb-status-filter").addEventListener("change", () => loadList());
    document.getElementById("reimb-create-btn").addEventListener("click", createReimb);
    loadList();
  }

  async function loadList() {
    const status = document.getElementById("reimb-status-filter").value;
    const q = status ? "?status=" + status : "";
    const data = await API.get("/reimbursements" + q);
    const el = document.getElementById("reimb-list");
    if (!data.items.length) { el.innerHTML = '<p class="muted">暂无报销单</p>'; return; }
    el.innerHTML = `<table>
      <thead><tr><th>单号</th><th>申请人</th><th>部门</th><th>金额</th><th>状态</th><th>结论</th><th>创建时间</th><th></th></tr></thead>
      <tbody>${data.items.map((r) => `
        <tr>
          <td>${r.no}</td><td>${r.applicant_name}</td><td>${r.department_name}</td>
          <td>¥${r.total_amount}</td>
          <td><span class="tag ${STATUS_CLASS[r.status] || ""}">${STATUS_TAG[r.status] || r.status}</span></td>
          <td>${r.conclusion || ""}</td>
          <td>${(r.created_at || "").slice(0, 16).replace("T", " ")}</td>
          <td><button class="btn btn-sm" data-open="${r.id}">查看</button></td>
        </tr>`).join("")}</tbody></table>`;
    el.querySelectorAll("[data-open]").forEach((b) => b.addEventListener("click", () => detail(b.dataset.open)));
  }

  async function createReimb() {
    const payload = {
      department_id: Number(document.getElementById("new-dept").value),
      project_id: document.getElementById("new-project").value ? Number(document.getElementById("new-project").value) : null,
      total_amount: document.getElementById("new-amount").value,
      items: [{
        cost_category_id: Number(document.getElementById("new-cat").value),
        amount: document.getElementById("new-amount").value,
        invoice_key: document.getElementById("new-invoice").value || null,
        description: document.getElementById("new-desc").value || null,
      }],
    };
    try {
      await API.post("/reimbursements", payload);
      App.toast("创建成功");
      render();
    } catch (e) { App.toast(e.message, true); }
  }

  async function detail(id) {
    const [r, base] = await Promise.all([API.get("/reimbursements/" + id), loadBase()]);
    const deptName = (base.depts.find((d) => d.id === r.department_id) || {}).name || r.department_id;
    const projName = r.project_id ? (base.projects.find((p) => p.id === r.project_id) || {}).name : null;
    const catName = (cid) => (base.cats.find((c) => c.id === cid) || {}).name || cid;
    const isFinance = Auth.hasRole("finance");
    const isOwner = r.applicant_id === Auth.user().id;
    const editable = isOwner && ["draft", "returned"].includes(r.status);
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="panel">
        <div class="flex-between">
          <h3>报销单 ${r.no} <span class="tag ${STATUS_CLASS[r.status] || ""}">${STATUS_TAG[r.status] || r.status}</span></h3>
          <div class="flex">
            <button id="back-btn" class="btn btn-sm">返回列表</button>
            ${r.status === "approved" ? `<a class="btn btn-sm btn-primary" href="/api/reimbursements/${r.id}/report" target="_blank">打开审核报告</a>` : ""}
          </div>
        </div>
        <div class="kv mt">
          <div><div class="k">申请人</div><div class="v">${r.applicant_id}</div></div>
          <div><div class="k">部门</div><div class="v">${deptName}</div></div>
          <div><div class="k">项目</div><div class="v">${projName || "—"}</div></div>
          <div><div class="k">总金额</div><div class="v">¥${r.total_amount}</div></div>
          <div><div class="k">退回原因</div><div class="v muted">${r.return_reason || "—"}</div></div>
        </div>
        <h4>明细</h4>
        <table><thead><tr><th>科目</th><th>金额</th><th>发票号</th><th>说明</th></tr></thead>
        <tbody>${r.items.map((it) => `<tr><td>${catName(it.cost_category_id)}</td><td>¥${it.amount}</td><td>${it.invoice_key || ""}</td><td>${it.description || ""}</td></tr>`).join("")}</tbody></table>
        <h4>附件（${r.attachments.length}）</h4>
        <div id="att-list">${r.attachments.map((a) => `<span class="tag tag-info">${a.category}</span> ${a.file_name} <button class="btn btn-sm" data-del-att="${a.attachment_id}">删除</button>&nbsp;`).join("") || '<span class="muted">无附件</span>'}</div>
        ${editable ? `
          <div class="mt">
            <h4>上传附件</h4>
            <div class="flex">
              <input id="att-files" type="file" multiple />
              <select id="att-cat">
                <option value="invoice">发票</option><option value="travel">行程单</option><option value="approval">审批单</option>
              </select>
              <button id="att-upload-btn" class="btn">上传</button>
            </div>
            <div class="form-actions">
              <button id="submit-btn" class="btn btn-primary">提交审核</button>
            </div>
          </div>` : ""}
        ${isFinance && r.status === "pending" ? `
          <div class="form-actions mt">
            <input id="return-reason" placeholder="退回原因" />
            <button id="return-btn" class="btn btn-danger">退回</button>
          </div>` : ""}
        ${isFinance && r.status === "manual_review" ? `
          <div class="form-actions mt">
            <input id="review-reason" placeholder="裁决说明（必填）" />
            <button id="review-ok-btn" class="btn btn-primary">裁决通过</button>
            <button id="review-return-btn" class="btn btn-danger">裁决退回</button>
          </div>` : ""}
        <div id="conclusion-box" class="mt"></div>
        <div id="task-box" class="mt"></div>
      </div>
    `;
    bindDetailEvents(r);
  }

  function bindDetailEvents(r) {
    document.getElementById("back-btn").addEventListener("click", () => render());
    const attList = document.getElementById("att-list");
    attList && attList.querySelectorAll("[data-del-att]").forEach((b) =>
      b.addEventListener("click", async () => {
        await API.del(`/reimbursements/${r.id}/attachments/${b.dataset.delAtt}`);
        App.toast("附件已删除"); detail(r.id);
      })
    );
    const uploadBtn = document.getElementById("att-upload-btn");
    uploadBtn && uploadBtn.addEventListener("click", async () => {
      const files = document.getElementById("att-files").files;
      if (!files.length) { App.toast("请选择文件", true); return; }
      const cat = document.getElementById("att-cat").value;
      const fd = new FormData();
      [...files].forEach((f) => fd.append("files", f));
      fd.append("categories", [...files].map(() => cat).join(","));
      await API.postForm(`/reimbursements/${r.id}/attachments`, fd);
      App.toast("上传成功"); detail(r.id);
    });
    const submitBtn = document.getElementById("submit-btn");
    submitBtn && submitBtn.addEventListener("click", async () => {
      try {
        const res = await API.post(`/reimbursements/${r.id}/submit`);
        App.toast("已提交，审核中…");
        pollTask(res.task_id);
      } catch (e) { App.toast(e.message, true); }
    });
    const returnBtn = document.getElementById("return-btn");
    returnBtn && returnBtn.addEventListener("click", async () => {
      const reason = document.getElementById("return-reason").value;
      if (!reason) { App.toast("请填写退回原因", true); return; }
      await API.post(`/reimbursements/${r.id}/return`, { reason });
      App.toast("已退回"); render();
    });
    const reviewOk = document.getElementById("review-ok-btn");
    reviewOk && reviewOk.addEventListener("click", () => review(r.id, "approved"));
    const reviewReturn = document.getElementById("review-return-btn");
    reviewReturn && reviewReturn.addEventListener("click", () => review(r.id, "returned"));
    showConclusion(r.conclusion);
  }

  async function review(id, conclusion) {
    const reason = document.getElementById("review-reason").value;
    if (!reason) { App.toast("请填写裁决说明", true); return; }
    await API.post(`/reimbursements/${id}/manual-review`, { conclusion, reason });
    App.toast("裁决完成"); render();
  }

  function showConclusion(c) {
    const box = document.getElementById("conclusion-box");
    if (!c) return;
    let html = `<h4>审核结论：<b>${c.result}</b></h4>`;
    if (c.recommended_category) {
      html += `<p>推荐科目：${JSON.stringify(c.recommended_category)}</p>`;
    }
    if (c.check_items && c.check_items.length) {
      html += `<h4>规则检查项</h4><table><thead><tr><th>规则</th><th>状态</th><th>说明</th></tr></thead><tbody>
        ${c.check_items.map((it) => `<tr><td>${it.code || ""}</td><td>${it.status || ""}</td><td>${it.message || ""}</td></tr>`).join("")}</tbody></table>`;
    }
    if (c.risk_items && c.risk_items.length) {
      html += `<h4>风险项</h4><table><thead><tr><th>风险</th><th>等级</th><th>说明</th></tr></thead><tbody>
        ${c.risk_items.map((it) => `<tr><td>${it.code || ""}</td><td>${it.level || ""}</td><td>${it.message || ""}</td></tr>`).join("")}</tbody></table>`;
    }
    box.innerHTML = html;
  }

  async function pollTask(taskId) {
    const box = document.getElementById("task-box");
    box.innerHTML = '<p class="muted">审核任务执行中…</p>';
    for (let i = 0; i < 40; i++) {
      await new Promise((res) => setTimeout(res, 1500));
      try {
        const t = await API.get("/audit-tasks/" + taskId);
        if (t.status === "done") {
          box.innerHTML = '<p class="text-ok">审核完成</p>';
          showConclusion(t.conclusion);
          if (t.conclusion && t.conclusion.result === "approved") {
            box.innerHTML += '<p class="text-ok">已通过，台账已写入，可打开审核报告查看详情</p>';
          }
          return;
        }
        if (t.status === "failed") {
          box.innerHTML = `<p class="text-danger">审核失败：${t.error || ""}</p>`;
          return;
        }
      } catch (e) { /* 继续轮询 */ }
    }
    box.innerHTML = '<p class="muted">任务仍在执行，请稍后刷新查看</p>';
  }

  return { render };
})();
