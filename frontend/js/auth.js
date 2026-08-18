/* 认证：登录 / 当前用户 / 退出 / 角色权限工具。 */
const Auth = (() => {
  let currentUser = null;

  async function login(username, password) {
    const data = await API.post("/auth/login", { username, password });
    API.setToken(data.access_token);
    currentUser = data.user;
    return data.user;
  }

  async function loadMe() {
    const me = await API.get("/auth/me");
    currentUser = me;
    return me;
  }

  async function logout() {
    try { await API.post("/auth/logout"); } catch (e) { /* 尽力而为 */ }
    API.setToken("");
    currentUser = null;
  }

  function user() { return currentUser; }
  function hasRole(role) { return !!currentUser && currentUser.roles.includes(role); }
  function hasAnyRole(roles) { return roles.some((r) => hasRole(r)); }
  function hasPerm(perm) { return !!currentUser && currentUser.permissions.includes(perm); }

  return { login, loadMe, logout, user, hasRole, hasAnyRole, hasPerm };
})();
