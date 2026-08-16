/* ═══════════════════════════════════════════════════════════
   CMS — common.js
   Thin fetch() wrapper around the Flask + SQLite backend
   (see app.py). The bundled dashboards work standalone with
   localStorage demo auth; this file is here so you can wire
   real API calls in as you extend the project — e.g.:

     const papers = await CMS.get('/api/papers');
     await CMS.post('/api/papers', {title, abstract, ...});

   All endpoints are defined in app.py and read/write to
   database/cms.db (see database/schema.sql for the schema).
   ═══════════════════════════════════════════════════════════ */

const CMS = (function () {
  const BASE = ""; // same-origin; Flask serves both pages and /api/*

  function authHeaders() {
    const session = JSON.parse(localStorage.getItem("cms_session") || "null");
    return session && session.token
      ? { Authorization: `Bearer ${session.token}` }
      : {};
  }

  async function request(path, options = {}) {
    const res = await fetch(BASE + path, {
      ...options,
      headers: {
        "Content-Type": "application/json",
        ...authHeaders(),
        ...(options.headers || {}),
      },
      body: options.body ? JSON.stringify(options.body) : undefined,
    });
    let data = null;
    try {
      data = await res.json();
    } catch (e) {
      /* no JSON body */
    }
    if (!res.ok) {
      const msg = (data && (data.error || data.message)) || `Request failed (${res.status})`;
      throw new Error(msg);
    }
    return data;
  }

  return {
    get: (path) => request(path, { method: "GET" }),
    post: (path, body) => request(path, { method: "POST", body }),
    put: (path, body) => request(path, { method: "PUT", body }),
    del: (path) => request(path, { method: "DELETE" }),

    // convenience wrappers matching app.py routes
    login: (email, password) => request("/api/login", { method: "POST", body: { email, password } }),
    register: (payload) => request("/api/register", { method: "POST", body: payload }),
    getConferences: () => request("/api/conferences", { method: "GET" }),
    createConference: (payload) => request("/api/conferences", { method: "POST", body: payload }),
    getPapers: () => request("/api/papers", { method: "GET" }),
    submitPaper: (payload) => request("/api/papers", { method: "POST", body: payload }),
    getReviews: () => request("/api/reviews", { method: "GET" }),
    submitReview: (payload) => request("/api/reviews", { method: "POST", body: payload }),
    getNotifications: () => request("/api/notifications", { method: "GET" }),
  };
})();
