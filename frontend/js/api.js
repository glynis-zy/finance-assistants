/* API 封装：JWT 携带、401 拦截、统一错误。 */
const API = (() => {
  const TOKEN_KEY = "fa_token";
  let token = localStorage.getItem(TOKEN_KEY) || "";

  function setToken(t) {
    token = t || "";
    if (t) localStorage.setItem(TOKEN_KEY, t);
    else localStorage.removeItem(TOKEN_KEY);
  }

  async function request(method, path, body, isForm) {
    const headers = {};
    if (token) headers["Authorization"] = "Bearer " + token;
    if (body != null && !isForm) headers["Content-Type"] = "application/json";
    let resp;
    try {
      resp = await fetch("/api" + path, {
        method,
        headers,
        body: isForm ? body : body != null ? JSON.stringify(body) : undefined,
      });
    } catch (e) {
      throw new Error("网络异常，请确认后端已启动");
    }
    if (resp.status === 401) {
      setToken("");
      if (location.hash !== "#/login") location.hash = "#/login";
      throw new Error("登录已过期，请重新登录");
    }
    if (resp.status === 204) return null;
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const err = new Error(data.message || "请求失败(" + resp.status + ")");
      err.data = data;
      throw err;
    }
    return data;
  }

  return {
    get: (p) => request("GET", p),
    post: (p, b) => request("POST", p, b),
    put: (p, b) => request("PUT", p, b),
    del: (p) => request("DELETE", p),
    postForm: (p, formData) => request("POST", p, formData, true),
    setToken,
    getToken: () => token,
  };
})();
