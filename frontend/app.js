(function () {
  const API = "/api/pc-build-agent/recommend";
  const SESSION_KEY = "pc_guide_session_id";

  const el = {
    form: document.getElementById("form-main"),
    query: document.getElementById("user-query"),
    btnSubmit: document.getElementById("btn-submit"),
    btnClearSession: document.getElementById("btn-clear-session"),
    loader: document.getElementById("loader"),
    sessionDisplay: document.getElementById("session-display"),
    clarifyWrap: document.getElementById("clarify-wrap"),
    clarifyContainer: document.getElementById("clarify-container"),
    resultWrap: document.getElementById("result-wrap"),
    resultInner: document.getElementById("result-inner"),
    debugHost: document.getElementById("debug-host"),
  };

  const chkDebug = document.getElementById("chk-debug-llm");
  if (chkDebug) {
    chkDebug.checked = localStorage.getItem("pc_guide_debug_llm") === "1";
    chkDebug.addEventListener("change", () => {
      localStorage.setItem("pc_guide_debug_llm", chkDebug.checked ? "1" : "0");
    });
  }

  function isDebugOn() {
    const chk = document.getElementById("chk-debug-llm");
    return !!(chk && chk.checked);
  }

  function clearDebugHost() {
    if (!el.debugHost) return;
    el.debugHost.innerHTML = "";
    el.debugHost.classList.add("hidden");
  }

  function buildDebugHtml(dbg) {
    if (!dbg || !dbg.enabled) return "";
    const steps = dbg.steps || [];
    let html = `<details class="debug-panel" open><summary>模型调试（请求 / 思维链 / 响应）</summary>`;
    if (dbg.note) html += `<p class="hint">${escapeHtml(dbg.note)}</p>`;
    if (dbg.model) html += `<p class="hint">当前模型：<code>${escapeHtml(dbg.model)}</code></p>`;
    steps.forEach((s, i) => {
      const am = s.assistant_message || {};
      const think = am.reasoning_content;
      const content = am.content || "";
      html += `<div class="debug-step"><h4>步骤 ${i + 1}：${escapeHtml(s.step || "")}</h4>`;
      if (s.usage) {
        html += `<p class="hint">usage：<code>${escapeHtml(JSON.stringify(s.usage))}</code></p>`;
      }
      if (s.parse_error) {
        html += `<div class="note-block danger"><h4>JSON 解析失败</h4><pre>${escapeHtml(s.parse_error)}</pre></div>`;
      }
      if (think) {
        html += `<div class="think-box"><strong>思维链（reasoning_content）</strong><pre>${escapeHtml(String(think))}</pre></div>`;
      } else {
        html += `<p class="hint">本步未返回 reasoning_content（常见于 deepseek-chat；推理模型如 deepseek-reasoner 更易出现该字段）。</p>`;
      }
      const msgs = (s.request && s.request.messages) || [];
      html += `<details class="debug-json"><summary>最终回复 content（原文）</summary><pre>${escapeHtml(String(content).slice(0, 50000))}</pre></details>`;
      html += `<details class="debug-json"><summary>请求 messages（JSON）</summary><pre>${escapeHtml(JSON.stringify(msgs, null, 2).slice(0, 80000))}</pre></details>`;
      html += `<details class="debug-json"><summary>完整步骤 JSON</summary><pre>${escapeHtml(JSON.stringify(s, null, 2).slice(0, 80000))}</pre></details>`;
      html += `</div>`;
    });
    html += `</details>`;
    return html;
  }

  function renderDebugHost(dbg) {
    if (!el.debugHost) return;
    if (!dbg || !dbg.enabled) {
      clearDebugHost();
      return;
    }
    el.debugHost.classList.remove("hidden");
    el.debugHost.innerHTML = buildDebugHtml(dbg);
  }

  function getSessionId() {
    return sessionStorage.getItem(SESSION_KEY) || "";
  }

  function setSessionId(id) {
    if (id) sessionStorage.setItem(SESSION_KEY, id);
    else sessionStorage.removeItem(SESSION_KEY);
    renderSession();
  }

  function renderSession() {
    const id = getSessionId();
    el.sessionDisplay.textContent = id ? id.slice(0, 8) + "…" : "（新会话）";
    el.sessionDisplay.title = id || "";
  }

  let selections = {};

  function resetSelections() {
    selections = {};
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function postRecommend(userQuery) {
    const body = {
      user_query: userQuery,
      session_id: getSessionId() || null,
      version: "v1",
      debug_llm: isDebugOn(),
    };
    const res = await fetch(API, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    if (!res.ok) {
      const t = await res.text();
      throw new Error(t || "请求失败 " + res.status);
    }
    return res.json();
  }

  function renderClarification(data) {
    el.clarifyWrap.classList.remove("hidden");
    el.resultWrap.classList.add("hidden");

    const q = data.clarification_question || "请补充以下信息：";
    const cards = data.clarification_cards || [];

    let html = `<p class="clarify-q">${escapeHtml(q)}</p>`;

    if (cards.length) {
      html += `<div class="card-grid">`;
      cards.forEach((card, idx) => {
        const cid = `c${idx}`;
        html += `<div class="choice-card" data-card-id="${cid}"><h3>${escapeHtml(card.title || card.id || "请选择")}</h3><div class="opt-list">`;
        (card.options || []).forEach((opt) => {
          const v = escapeHtml(opt.value || "");
          const lab = escapeHtml(opt.label || opt.value || "");
          html += `<button type="button" class="opt-btn" data-value="${v}" data-label="${lab}">${lab}</button>`;
        });
        html += `</div></div>`;
      });
      html += `</div>`;
      html += `<p class="hint">点选选项后会记入下方输入框；也可直接修改文案再提交。</p>`;
    } else {
      html += `<p class="hint">请在左侧输入框补充预算、用途、是否要显示器等信息后再次提交。</p>`;
    }

    el.clarifyContainer.innerHTML = html;
    renderDebugHost(data.debug_llm);

    el.clarifyContainer.querySelectorAll(".opt-btn").forEach((btn) => {
      btn.addEventListener("click", () => {
        const cardEl = btn.closest(".choice-card");
        const cardId = cardEl ? cardEl.getAttribute("data-card-id") || "" : "";
        const multi = false;
        if (!multi && cardEl) {
          cardEl.querySelectorAll(".opt-btn").forEach((b) => b.classList.remove("selected"));
        }
        btn.classList.add("selected");
        selections[cardId] = {
          value: btn.getAttribute("data-value"),
          label: btn.getAttribute("data-label"),
        };
        applySelectionsToQuery();
      });
    });
  }

  function applySelectionsToQuery() {
    const parts = Object.keys(selections)
      .sort()
      .map((k) => selections[k].label)
      .filter(Boolean);
    if (parts.length) {
      const prefix = el.query.value.trim() ? el.query.value.trim() + "\n" : "";
      el.query.value = prefix + parts.join("；") + "。";
    }
  }

  function renderMarkdown(md) {
    if (!md || !window.marked) return `<div class="md-body">${escapeHtml(md)}</div>`;
    try {
      return `<div class="md-body">${marked.parse(md, { headerIds: false })}</div>`;
    } catch {
      return `<div class="md-body">${escapeHtml(md)}</div>`;
    }
  }

  function renderSuccess(payload) {
    el.clarifyWrap.classList.add("hidden");
    el.resultWrap.classList.remove("hidden");
    clearDebugHost();

    const d = payload.data || {};
    if (d.session_id) setSessionId(d.session_id);

    const summary = escapeHtml(d.requirement_summary || "");
    const w = d.weights || {};
    const weightTags = ["performance", "price", "appearance", "other"]
      .filter((k) => w[k] != null)
      .map((k) => `<span class="weight-tag">${escapeHtml(k)} ${Number(w[k]).toFixed(2)}</span>`)
      .join("");

    const explain = escapeHtml(d.weights_explanation || "");

    let html = "";

    html += `<div class="summary-bar">`;
    html += `<div><strong>需求摘要：</strong>${summary || "—"}</div>`;
    if (weightTags) html += `<div class="weights">${weightTags}</div>`;
    if (explain) html += `<div style="margin-top:8px;color:#666;">${explain}</div>`;
    html += `</div>`;

    const status = d.status || payload.message || "";
    const total = Number(d.total_price || 0);
    html += `<div class="price-banner">`;
    html += `<span class="label">参考总价（含所选配件）</span>`;
    html += `<span class="amt">¥${total.toFixed(0)}</span>`;
    html += `<span class="status">${escapeHtml(status)}</span>`;
    html += `</div>`;

    const lines = d.final_build || [];
    if (lines.length) {
      html += `<div class="parts-table-wrap"><table class="parts-table"><thead><tr>`;
      html += `<th>类别</th><th>配件</th><th class="col-price">参考价</th><th>数量</th><th>购买</th>`;
      html += `</tr></thead><tbody>`;
      lines.forEach((row) => {
        const url = row.jd_url || "#";
        const link =
          url && url !== "#"
            ? `<a class="jd-link" href="${escapeHtml(url)}" target="_blank" rel="noopener">京东示意</a>`
            : `<span class="text-muted">链接占位</span>`;
        html += `<tr>`;
        html += `<td>${escapeHtml(row.category)}</td>`;
        html += `<td>${escapeHtml(row.name)}</td>`;
        html += `<td class="col-price">¥${Number(row.price).toFixed(0)}</td>`;
        html += `<td>${row.quantity ?? 1}</td>`;
        html += `<td class="col-actions">${link}</td>`;
        html += `</tr>`;
      });
      html += `</tbody></table></div>`;
    }

    const compat = d.compatibility_notes || [];
    const risks = d.risk_notes || [];
    const reasons = d.recommendation_reason || [];

    if (reasons.length) {
      html += `<div class="note-block info"><h4>推荐理由</h4><ul>`;
      reasons.forEach((r) => (html += `<li>${escapeHtml(r)}</li>`));
      html += `</ul></div>`;
    }

    if (compat.length) {
      html += `<div class="note-block info"><h4>兼容性说明</h4><ul>`;
      compat.forEach((r) => (html += `<li>${escapeHtml(r)}</li>`));
      html += `</ul></div>`;
    }

    if (risks.length) {
      html += `<div class="note-block warn"><h4>风险提示</h4><ul>`;
      risks.forEach((r) => (html += `<li>${escapeHtml(r)}</li>`));
      html += `</ul></div>`;
    }

    if (d.status === "need_user_confirmation") {
      html += `<div class="note-block warn"><h4>需要你确认</h4><p>当前方案略超预算上限，若你接受小幅超支可继续；否则请说明「严格不超预算」以便进一步降配。</p></div>`;
    }

    const alts = d.alternative_suggestions || [];
    if (alts.length) {
      html += `<div class="note-block danger"><h4>替代建议</h4><ul>`;
      alts.forEach((r) => (html += `<li>${escapeHtml(r)}</li>`));
      html += `</ul></div>`;
    }

    const md = d.recommendation_markdown || "";
    if (md) {
      html += `<h3 style="margin-top:20px;font-size:15px;">详细说明</h3>`;
      html += renderMarkdown(md);
    }

    html += buildDebugHtml(d.debug_llm);

    el.resultInner.innerHTML = html;
  }

  function renderFailed(payload) {
    el.clarifyWrap.classList.add("hidden");
    el.resultWrap.classList.remove("hidden");
    clearDebugHost();
    const d = payload.data || {};
    if (d.session_id) setSessionId(d.session_id);

    let html = `<div class="note-block danger"><h4>暂无法生成闭环方案</h4>`;
    html += `<p>${escapeHtml(payload.message || "failed")}</p>`;
    const alts = d.alternative_suggestions || [];
    if (alts.length) {
      html += `<ul>`;
      alts.forEach((a) => (html += `<li>${escapeHtml(a)}</li>`));
      html += `</ul>`;
    }
    const md = d.recommendation_markdown || "";
    if (md) html += renderMarkdown(md);
    html += `</div>`;
    html += buildDebugHtml(d.debug_llm);
    el.resultInner.innerHTML = html;
  }

  async function onSubmit(e) {
    e.preventDefault();
    const q = el.query.value.trim();
    if (!q) {
      alert("请先描述你的装机需求（预算、用途、是否要显示器等）。");
      return;
    }

    el.btnSubmit.disabled = true;
    el.loader.classList.add("on");
    clearDebugHost();

    try {
      const json = await postRecommend(q);
      const data = json.data || {};

      if (json.code !== 0 && json.message === "parse_failed") {
        renderFailed(json);
        return;
      }

      if (data.need_clarification) {
        resetSelections();
        renderClarification(data);
        return;
      }

      if (json.message === "failed_with_alternative" || data.status === "failed_with_alternative") {
        renderSuccess(json);
        return;
      }

      renderSuccess(json);
    } catch (err) {
      el.resultWrap.classList.remove("hidden");
      el.clarifyWrap.classList.add("hidden");
      el.resultInner.innerHTML = `<div class="note-block danger"><h4>请求出错</h4><pre style="white-space:pre-wrap;">${escapeHtml(
        String(err)
      )}</pre></div>`;
    } finally {
      el.btnSubmit.disabled = false;
      el.loader.classList.remove("on");
    }
  }

  el.form.addEventListener("submit", onSubmit);

  el.btnClearSession.addEventListener("click", () => {
    setSessionId("");
    resetSelections();
    el.clarifyWrap.classList.add("hidden");
    el.resultWrap.classList.add("hidden");
    el.resultInner.innerHTML = "";
    el.clarifyContainer.innerHTML = "";
    clearDebugHost();
  });

  renderSession();
})();
