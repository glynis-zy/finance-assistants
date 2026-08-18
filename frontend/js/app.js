/* 应用骨架：hash 路由、权限菜单、登录/主视图切换。 */
const App = (() => {
  const routes = {
    reimb: { title: "报销审核", render: () => Reimb.render(), visible: () => Auth.hasAnyRole(["applicant", "finance"]) },
    budget: { title: "预算监控", render: () => BudgetPanel.render(), visible: () => Auth.hasAnyRole(["budget_manager", "finance"]) },
    ar: { title: "应收预警", render: () => ArPanel.render(), visible: () => Auth.hasAnyRole(["ar_specialist", "finance"]) },
    alerts: { title: "预警中心", render: () => Alerts.render(), visible: () => Auth.hasPerm("alert:view") },
    admin: { title: "系统管理", render: () => Admin.render(), visible: () => Auth.hasAnyRole(["admin"]) },
  };

  function toast(msg, isError) {
    const el = document.getElementById("toast");
    el.textContent = msg;
    el.className = "toast" + (isError ? " error" : "");
    clearTimeout(toast._t);
    toast._t = setTimeout(() => el.classList.add("hidden"), 2600);
  }

  function renderMenu() {
    const menu = document.getElementById("menu");
    const route = location.hash.replace("#/", "") || "reimb";
    menu.innerHTML = Object.entries(routes)
      .filter(([, r]) => r.visible())
      .map(
        ([key, r]) =>
          `<a data-route="${key}" class="${key === route ? "active" : ""}">${r.title}</a>`
      )
      .join("");
    menu.querySelectorAll("a").forEach((a) =>
      a.addEventListener("click", () => (location.hash = "#/" + a.dataset.route))
    );
  }

  async function navigate() {
    const route = location.hash.replace("#/", "") || "reimb";
    const conf = routes[route];
    if (!conf || !conf.visible()) {
      location.hash = "#/reimb";
      return;
    }
    renderMenu();
    document.getElementById("page-title").textContent = conf.title;
    const content = document.getElementById("content");
    try {
      await conf.render();
    } catch (e) {
      content.innerHTML = `<div class="panel"><span class="text-danger">${e.message}</span></div>`;
    }
  }

  async function boot() {
    document.getElementById("login-btn").addEventListener("click", doLogin);
    document.getElementById("logout-btn").addEventListener("click", doLogout);
    document.getElementById("login-password").addEventListener("keydown", (e) => {
      if (e.key === "Enter") doLogin();
    });
    window.addEventListener("hashchange", () => {
      if (Auth.user()) navigate();
    });

    if (!API.getToken()) {
      showLogin();
      return;
    }
    try {
      const me = await Auth.loadMe();
      enterApp(me);
    } catch (e) {
      showLogin();
    }
  }

  async function doLogin() {
    const username = document.getElementById("login-username").value.trim();
    const password = document.getElementById("login-password").value;
    document.getElementById("login-error").textContent = "";
    if (!username || !password) {
      document.getElementById("login-error").textContent = "请输入用户名与密码";
      return;
    }
    try {
      const me = await Auth.login(username, password);
      enterApp(me);
    } catch (e) {
      document.getElementById("login-error").textContent = e.message;
    }
  }

  async function doLogout() {
    await Auth.logout();
    showLogin();
  }

  function enterApp(me) {
    document.getElementById("login-view").classList.add("hidden");
    document.getElementById("app-view").classList.remove("hidden");
    document.getElementById("user-name").textContent = me.name + "（" + me.username + "）";
    document.getElementById("user-role").textContent = me.roles.join(" / ");
    if (!location.hash || location.hash === "#/login") location.hash = "#/reimb";
    navigate();
  }

  function showLogin() {
    document.getElementById("app-view").classList.add("hidden");
    document.getElementById("login-view").classList.remove("hidden");
    document.getElementById("login-password").value = "";
    location.hash = "#/login";
  }

  return { boot, toast };
})();

document.addEventListener("DOMContentLoaded", () => App.boot());
