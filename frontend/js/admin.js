/* 系统管理（admin）：用户 / 角色 / 系统参数 / 费用科目。 */
const Admin = (() => {
  async function render() {
    const content = document.getElementById("content");
    content.innerHTML = `
      <div class="panel">
        <div class="flex-between">
          <h3>用户管理</h3>
          <button id="user-new-btn" class="btn btn-primary btn-sm">新建用户</button>
        </div>
        <div id="user-list" class="mt"></div>
      </div>
      <div class="panel">
        <h3>角色与权限</h3>
        <div id="role-list"></div>
      </div>
      <div class="panel">
        <h3>系统参数</h3>
        <div id="param-list"></div>
      </div>
      <div class="panel">
        <h3>费用科目</h3>
        <div id="cat-list"></div>
      </div>
      <div id="user-form-box"></div>
    `;
    loadUsers();
    loadRoles();
    loadParams();
    loadCats();
    document.getElementById("user-new-btn").addEventListener("click", showUserForm);
  }

  async function loadUsers() {
    const data = await API.get("/users");
    const el = document.getElementById("user-list");
    el.innerHTML = `<table>
      <thead><tr><th>ID</th><th>用户名</th><th>姓名</th><th>角色</th><th>启用</th></tr></thead>
      <tbody>${data.map((u) => `
        <tr><td>${u.id}</td><td>${u.username}</td><td>${u.name}</td>
        <td>${u.roles.map((r) => `<span class="tag tag-info">${r}</span>`).join(" ")}</td>
        <td>${u.enabled ? "是" : "否"}</td></tr>`).join("")}</tbody></table>`;
  }

  async function loadRoles() {
    const data = await API.get("/roles");
    const el = document.getElementById("role-list");
    el.innerHTML = `<table>
      <thead><tr><th>角色</th><th>名称</th><th>权限码</th></tr></thead>
      <tbody>${data.map((r) => `
        <tr><td><b>${r.code}</b></td><td>${r.name}</td><td class="muted">${r.permissions.join("、")}</td></tr>`).join("")}</tbody></table>`;
  }

  async function loadParams() {
    const data = await API.get("/sys-params");
    const el = document.getElementById("param-list");
    if (!data.length) { el.innerHTML = '<p class="muted">暂无参数</p>'; return; }
    el.innerHTML = `<table>
      <thead><tr><th>键</th><th>值</th><th>类型</th><th>说明</th><th></th></tr></thead>
      <tbody>${data.map((p) => `
        <tr>
          <td>${p.key}</td>
          <td><input data-param-key="${p.key}" data-param-type="${p.value_type}" value="${p.value}" class="param-input" style="width:110px" /></td>
          <td>${p.value_type}</td><td class="muted">${p.description || ""}</td>
          <td><button class="btn btn-sm btn-primary" data-save-param="${p.key}">保存</button></td>
        </tr>`).join("")}</tbody></table>`;
    el.querySelectorAll("[data-save-param]").forEach((b) =>
      b.addEventListener("click", async () => {
        const input = el.querySelector(`[data-param-key="${b.dataset.saveParam}"]`);
        await API.put("/sys-params/" + b.dataset.saveParam, { value: input.value });
        App.toast("参数已更新（审计留痕）");
      })
    );
  }

  async function loadCats() {
    const data = await API.get("/cost-categories?enabled_only=false");
    const el = document.getElementById("cat-list");
    el.innerHTML = `<table>
      <thead><tr><th>ID</th><th>编码</th><th>名称</th><th>启用</th><th></th></tr></thead>
      <tbody>${data.map((c) => `
        <tr><td>${c.id}</td><td>${c.code}</td><td>${c.name}</td>
        <td>${c.enabled ? "是" : "否"}</td>
        <td><button class="btn btn-sm" data-toggle-cat="${c.id}" data-enabled="${c.enabled}">${c.enabled ? "停用" : "启用"}</button></td></tr>`).join("")}</tbody></table>`;
    el.querySelectorAll("[data-toggle-cat]").forEach((b) =>
      b.addEventListener("click", async () => {
        await API.put("/cost-categories/" + b.dataset.toggleCat, { enabled: b.dataset.enabled === "true" ? false : true });
        App.toast("科目状态已更新"); loadCats();
      })
    );
  }

  function showUserForm() {
    const box = document.getElementById("user-form-box");
    box.innerHTML = `
      <div class="panel">
        <h3>新建用户</h3>
        <div class="form-grid">
          <div class="form-item"><label>用户名</label><input id="uf-username" /></div>
          <div class="form-item"><label>姓名</label><input id="uf-name" /></div>
          <div class="form-item"><label>密码（≥6 位）</label><input id="uf-password" type="password" /></div>
          <div class="form-item"><label>角色</label>
            <select id="uf-role"><option value="applicant">applicant</option><option value="finance">finance</option><option value="budget_manager">budget_manager</option><option value="ar_specialist">ar_specialist</option><option value="admin">admin</option></select>
          </div>
        </div>
        <div class="form-actions">
          <button id="uf-save" class="btn btn-primary">创建</button>
          <button id="uf-cancel" class="btn">取消</button>
        </div>
      </div>`;
    document.getElementById("uf-save").addEventListener("click", async () => {
      try {
        await API.post("/users", {
          username: document.getElementById("uf-username").value.trim(),
          name: document.getElementById("uf-name").value.trim(),
          password: document.getElementById("uf-password").value,
          roles: [document.getElementById("uf-role").value],
        });
        App.toast("用户已创建");
        render();
      } catch (e) { App.toast(e.message, true); }
    });
    document.getElementById("uf-cancel").addEventListener("click", () => (box.innerHTML = ""));
  }

  return { render };
})();
