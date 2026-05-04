/**
 * 装机导购前端主逻辑。
 * 依赖：marked（CDN）、config.js 设置的 window.PC_GUIDE_API_BASE
 */
(function () {
  // —— 与后端通信：根据 config.js 注入的基址拼接 recommend 接口完整 URL ——
  function recommendUrl() {
    var base = String(window.PC_GUIDE_API_BASE || "").replace(/\/+$/, ""); // 读取全局基址并去尾斜杠
    if (!base) {
      // 未配置时返回空字符串，后续 fetch 会失败并在 catch 中提示用户检查 config.js
      return "";
    }
    return base + "/api/pc-build-agent/recommend"; // 与 FastAPI 路由 recommend_endpoint 一致
  }

  // sessionStorage 键名：保存后端返回的 session_id，实现多轮对话
  var SESSION_KEY = "pc_guide_session_id";

  // 缓存 DOM 引用，避免重复 querySelector/getElementById 提升可读性与微性能
  var el = {
    form: document.getElementById("form-main"), // 主表单：submit 触发推荐
    query: document.getElementById("user-query"), // 用户自然语言输入
    btnSubmit: document.getElementById("btn-submit"), // 提交按钮：请求期间禁用防重复点击
    btnClearSession: document.getElementById("btn-clear-session"), // 清空会话与界面
    loader: document.getElementById("loader"), // 加载动画容器
    sessionDisplay: document.getElementById("session-display"), // 展示截断后的 session_id
    clarifyWrap: document.getElementById("clarify-wrap"), // 追问区域外层
    clarifyContainer: document.getElementById("clarify-container"), // 追问文案与卡片注入点
    resultWrap: document.getElementById("result-wrap"), // 结果区外层
    resultInner: document.getElementById("result-inner"), // 结果 HTML 注入点
    debugHost: document.getElementById("debug-host"), // 追问态下调试面板挂载点（与结果区分离）
  };

  // 调试勾选框：从 localStorage 恢复用户上次选择，持久化在浏览器本地
  var chkDebug = document.getElementById("chk-debug-llm");
  if (chkDebug) {
    chkDebug.checked = localStorage.getItem("pc_guide_debug_llm") === "1"; // "1" 表示开启
    chkDebug.addEventListener("change", function () {
      localStorage.setItem("pc_guide_debug_llm", chkDebug.checked ? "1" : "0"); // 同步写入本地存储
    });
  }

  // 读取当前是否勾选调试：每次请求重新读取，避免闭包陈旧状态
  function isDebugOn() {
    var chk = document.getElementById("chk-debug-llm"); // 再次获取防止热更新 DOM（防御式）
    return !!(chk && chk.checked); // 双否定转布尔
  }

  // 清空追问区域下方的调试宿主节点并隐藏
  function clearDebugHost() {
    if (!el.debugHost) {
      return; // 无该节点则跳过（兼容残缺 HTML）
    }
    el.debugHost.innerHTML = ""; // 移除子节点释放事件引用
    el.debugHost.classList.add("hidden"); // 使用 CSS .hidden 控制显示
  }

  // 将后端返回的 debug_llm 对象渲染为可折叠 HTML 字符串
  function buildDebugHtml(dbg) {
    if (!dbg || !dbg.enabled) {
      return ""; // 未开启调试则返回空串，调用方不插入面板
    }
    var steps = dbg.steps || []; // 模型调用步骤数组，每项含 request/assistant_message 等
    var html = '<details class="debug-panel" open><summary>模型调试（请求 / 思维链 / 响应）</summary>'; // open 默认展开
    if (dbg.note) {
      html += '<p class="hint">' + escapeHtml(dbg.note) + "</p>"; // 服务端提示勿在生产暴露
    }
    if (dbg.model) {
      html += '<p class="hint">当前模型：<code>' + escapeHtml(dbg.model) + "</code></p>"; // 展示模型名
    }
    steps.forEach(function (s, i) {
      var am = s.assistant_message || {}; // OpenAI 兼容消息体
      var think = am.reasoning_content; // 推理模型思维链字段（可能为空）
      var content = am.content || ""; // 最终 JSON 文本内容
      html += '<div class="debug-step"><h4>步骤 ' + (i + 1) + "：" + escapeHtml(s.step || "") + "</h4>"; // 步骤标题
      if (s.usage) {
        html += '<p class="hint">usage：<code>' + escapeHtml(JSON.stringify(s.usage)) + "</code></p>"; // token 用量
      }
      if (s.parse_error) {
        html += '<div class="note-block danger"><h4>JSON 解析失败</h4><pre>' + escapeHtml(s.parse_error) + "</pre></div>"; // 解析异常信息
      }
      if (think) {
        html +=
          '<div class="think-box"><strong>思维链（reasoning_content）</strong><pre>' +
          escapeHtml(String(think)) +
          "</pre></div>"; // 展示思维链全文
      } else {
        html +=
          '<p class="hint">本步未返回 reasoning_content（常见于 deepseek-chat；推理模型如 deepseek-reasoner 更易出现该字段）。</p>'; // 说明无思维链
      }
      var msgs = (s.request && s.request.messages) || []; // 发给模型的 messages 数组
      html +=
        '<details class="debug-json"><summary>最终回复 content（原文）</summary><pre>' +
        escapeHtml(String(content).slice(0, 50000)) +
        "</pre></details>"; // 限制长度防页面卡死
      html +=
        '<details class="debug-json"><summary>请求 messages（JSON）</summary><pre>' +
        escapeHtml(JSON.stringify(msgs, null, 2).slice(0, 80000)) +
        "</pre></details>"; // 格式化 JSON 截断
      html +=
        '<details class="debug-json"><summary>完整步骤 JSON</summary><pre>' +
        escapeHtml(JSON.stringify(s, null, 2).slice(0, 80000)) +
        "</pre></details>"; // 整步调试快照
      html += "</div>"; // 关闭 debug-step
    });
    html += "</details>"; // 关闭最外层 details
    return html; // 返回拼接好的 HTML 字符串
  }

  // 将调试 HTML 写入 clarify 流程下的 debugHost 并显示
  function renderDebugHost(dbg) {
    if (!el.debugHost) {
      return; // 无容器不渲染
    }
    if (!dbg || !dbg.enabled) {
      clearDebugHost(); // 关闭调试时清理
      return;
    }
    el.debugHost.classList.remove("hidden"); // 显示调试区
    el.debugHost.innerHTML = buildDebugHtml(dbg); // 注入 HTML（信任后端调试数据，生产勿开）
  }

  // 从 sessionStorage 读取会话 id，无则返回空串
  function getSessionId() {
    return sessionStorage.getItem(SESSION_KEY) || "";
  }

  // 写入或清除 session_id 并刷新页眉展示
  function setSessionId(id) {
    if (id) {
      sessionStorage.setItem(SESSION_KEY, id); // 持久化到浏览器会话级存储
    } else {
      sessionStorage.removeItem(SESSION_KEY); // 用户点击清空会话
    }
    renderSession(); // 更新截断显示与 title 全量 id
  }

  // 根据当前 sessionStorage 更新 UI 上的会话摘要
  function renderSession() {
    var id = getSessionId(); // 读取原始 UUID 字符串
    el.sessionDisplay.textContent = id ? id.slice(0, 8) + "…" : "（新会话）"; // 隐私与美观：仅显示前缀
    el.sessionDisplay.title = id || ""; // 鼠标悬停可看完整 id 便于排错
  }

  // 追问卡片当前选中项：键为卡片占位 id，值为 {value,label}
  var selections = {};

  // 新一轮追问前重置卡片选择状态
  function resetSelections() {
    selections = {}; // 丢弃旧引用
  }

  // HTML 转义：防 XSS，所有用户/模型文本插入 innerHTML 前须经过此函数
  function escapeHtml(s) {
    return String(s) // 非字符串转字符串
      .replace(/&/g, "&amp;") // 和号最先替换，避免连锁替换问题
      .replace(/</g, "&lt;") // 小于号
      .replace(/>/g, "&gt;") // 大于号
      .replace(/"/g, "&quot;"); // 双引号
  }

  // POST recommend：携带 user_query、session_id、debug_llm
  async function postRecommend(userQuery) {
    var url = recommendUrl(); // 计算完整接口地址
    if (!url) {
      throw new Error("未配置 PC_GUIDE_API_BASE：请编辑 frontend/config.js 中的后端根地址。"); // 明确配置缺失
    }
    var body = {
      user_query: userQuery, // 与 Pydantic RecommendRequest.user_query 对齐
      session_id: getSessionId() || null, // 首轮传 null 由后端建 session
      version: "v1", // 协议版本字段占位
      debug_llm: isDebugOn(), // 勾选则请求携带调试轨迹
    };
    var res = await fetch(url, {
      method: "POST", // REST 语义：创建一次推荐计算
      headers: { "Content-Type": "application/json" }, // 告知 FastAPI 解析 JSON body
      body: JSON.stringify(body), // 序列化请求体
    });
    if (!res.ok) {
      var t = await res.text(); // 尽力读取错误正文（可能为 HTML 或纯文本）
      throw new Error(t || "请求失败 " + res.status); // 抛出至 onSubmit catch
    }
    return res.json(); // 解析 JSON 为对象
  }

  // 渲染追问态：展示问题、可选卡片，并绑定选项点击
  function renderClarification(data) {
    el.clarifyWrap.classList.remove("hidden"); // 显示追问容器
    el.resultWrap.classList.add("hidden"); // 隐藏右侧结果，避免同时抢占视觉焦点

    var q = data.clarification_question || "请补充以下信息："; // 后端生成或默认追问句
    var cards = data.clarification_cards || []; // 结构化卡片数组

    var html = '<p class="clarify-q">' + escapeHtml(q) + "</p>"; // 追问主文案

    if (cards.length) {
      html += '<div class="card-grid">'; // 卡片栅格容器
      cards.forEach(function (card, idx) {
        var cid = "c" + idx; // 本地生成的卡片实例 id，用于 selections 键
        html +=
          '<div class="choice-card" data-card-id="' +
          cid +
          '"><h3>' +
          escapeHtml(card.title || card.id || "请选择") +
          '</h3><div class="opt-list">'; // 卡片标题
        (card.options || []).forEach(function (opt) {
          var v = escapeHtml(opt.value || ""); // 选项 machine value
          var lab = escapeHtml(opt.label || opt.value || ""); // 展示文案
          html +=
            '<button type="button" class="opt-btn" data-value="' +
            v +
            '" data-label="' +
            lab +
            '">' +
            lab +
            "</button>"; // 每个可点选项
        });
        html += "</div></div>"; // 关闭 opt-list 与 choice-card
      });
      html += "</div>"; // 关闭 card-grid
      html += '<p class="hint">点选选项后会记入下方输入框；也可直接修改文案再提交。</p>'; // 操作说明
    } else {
      html += '<p class="hint">请在左侧输入框补充预算、用途、是否要显示器等信息后再次提交。</p>'; // 无卡片时指引
    }

    el.clarifyContainer.innerHTML = html; // 一次性写入卡片 DOM
    renderDebugHost(data.debug_llm); // 追问也可能带调试信息

    el.clarifyContainer.querySelectorAll(".opt-btn").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var cardEl = btn.closest(".choice-card"); // 找到所属卡片根节点
        var cardId = cardEl ? cardEl.getAttribute("data-card-id") || "" : ""; // 读取卡片 id
        var multi = false; // 当前 UI 未实现多选，占位与后端 multi_select 对齐可后续扩展
        if (!multi && cardEl) {
          cardEl.querySelectorAll(".opt-btn").forEach(function (b) {
            b.classList.remove("selected"); // 单选：清除同卡其他按钮高亮
          });
        }
        btn.classList.add("selected"); // 标记当前选项
        selections[cardId] = {
          value: btn.getAttribute("data-value"), // 记录 value
          label: btn.getAttribute("data-label"), // 记录 label 供拼回输入框
        };
        applySelectionsToQuery(); // 同步到 textarea
      });
    });
  }

  // 将已选卡片 label 合并写入用户输入框，减少用户手打
  function applySelectionsToQuery() {
    var parts = Object.keys(selections) // 取所有已选卡片 key
      .sort() // 稳定顺序
      .map(function (k) {
        return selections[k].label; // 只取展示文案
      })
      .filter(Boolean); // 去掉空
    if (parts.length) {
      var prefix = el.query.value.trim() ? el.query.value.trim() + "\n" : ""; // 保留用户已输入内容
      el.query.value = prefix + parts.join("；") + "。"; // 中文分号连接并以句号收尾
    }
  }

  // Markdown 渲染：优先 marked，失败则纯文本转义
  function renderMarkdown(md) {
    if (!md || !window.marked) {
      return '<div class="md-body">' + escapeHtml(md) + "</div>"; // 无 marked 时退化为纯文本块
    }
    try {
      return '<div class="md-body">' + marked.parse(md, { headerIds: false }) + "</div>"; // 禁用 header id 降低冲突
    } catch (_e) {
      return '<div class="md-body">' + escapeHtml(md) + "</div>"; // 解析异常兜底
    }
  }

  // 渲染成功/部分成功（含 failed_with_alternative）的右侧结果区
  function renderSuccess(payload) {
    el.clarifyWrap.classList.add("hidden"); // 关闭追问区
    el.resultWrap.classList.remove("hidden"); // 打开结果区
    clearDebugHost(); // 成功态调试信息通常插在 resultInner 内，此处先清追问区调试点

    var d = payload.data || {}; // 解包 data，防 undefined
    if (d.session_id) {
      setSessionId(d.session_id); // 后端可能新建或延续 session
    }

    var summary = escapeHtml(d.requirement_summary || ""); // 需求摘要纯文本
    var w = d.weights || {}; // 四维权重对象
    var weightTags = ["performance", "price", "appearance", "other"] // 固定顺序展示
      .filter(function (k) {
        return w[k] != null; // 过滤未返回维度
      })
      .map(function (k) {
        return '<span class="weight-tag">' + escapeHtml(k) + " " + Number(w[k]).toFixed(2) + "</span>"; // 保留两位小数
      })
      .join(""); // 拼成一串 HTML

    var explain = escapeHtml(d.weights_explanation || ""); // 模型对权重的自然语言解释

    var html = ""; // 累积结果 HTML

    html += '<div class="summary-bar">'; // 顶部摘要条
    html += '<div><strong>需求摘要：</strong>' + (summary || "—") + "</div>"; // 摘要主体
    if (weightTags) {
      html += '<div class="weights">' + weightTags + "</div>"; // 权重标签组
    }
    if (explain) {
      html += '<div style="margin-top:8px;color:#666;">' + explain + "</div>"; // 灰色小字说明
    }
    html += "</div>"; // 关闭 summary-bar

    var status = d.status || payload.message || ""; // 业务状态或顶层 message
    var total = Number(d.total_price || 0); // 数值化总价，防字符串
    html += '<div class="price-banner">'; // 价格横幅
    html += '<span class="label">参考总价（含所选配件）</span>'; // 文案
    html += '<span class="amt">¥' + total.toFixed(0) + "</span>"; // 整数元展示
    html += '<span class="status">' + escapeHtml(status) + "</span>"; // 状态原样展示
    html += "</div>"; // 关闭 price-banner

    var lines = d.final_build || []; // 装机清单行数组
    if (lines.length) {
      html += '<div class="parts-table-wrap"><table class="parts-table"><thead><tr>'; // 表格外层
      html += '<th>类别</th><th>配件</th><th class="col-price">参考价</th><th>数量</th><th>购买</th>'; // 表头
      html += "</tr></thead><tbody>"; // 进入表体
      lines.forEach(function (row) {
        var url = row.jd_url || "#"; // 京东链接占位
        var link =
          url && url !== "#"
            ? '<a class="jd-link" href="' + escapeHtml(url) + '" target="_blank" rel="noopener">京东示意</a>' // 新窗口打开
            : '<span class="text-muted">链接占位</span>'; // 无链接
        html += "<tr>"; // 新行
        html += "<td>" + escapeHtml(row.category) + "</td>"; // 品类列
        html += "<td>" + escapeHtml(row.name) + "</td>"; // 名称列
        html += '<td class="col-price">¥' + Number(row.price).toFixed(0) + "</td>"; // 价格列
        html += "<td>" + (row.quantity ?? 1) + "</td>"; // 数量列，空则 1
        html += '<td class="col-actions">' + link + "</td>"; // 操作列
        html += "</tr>"; // 结束行
      });
      html += "</tbody></table></div>"; // 关闭 table
    }

    var compat = d.compatibility_notes || []; // 兼容性要点列表
    var risks = d.risk_notes || []; // 风险要点列表
    var reasons = d.recommendation_reason || []; // 推荐理由列表

    if (reasons.length) {
      html += '<div class="note-block info"><h4>推荐理由</h4><ul>'; // 信息样式块
      reasons.forEach(function (r) {
        html += "<li>" + escapeHtml(r) + "</li>"; // 列表项
      });
      html += "</ul></div>"; // 关闭块
    }

    if (compat.length) {
      html += '<div class="note-block info"><h4>兼容性说明</h4><ul>'; // 兼容说明
      compat.forEach(function (r) {
        html += "<li>" + escapeHtml(r) + "</li>";
      });
      html += "</ul></div>";
    }

    if (risks.length) {
      html += '<div class="note-block warn"><h4>风险提示</h4><ul>'; // 警告样式
      risks.forEach(function (r) {
        html += "<li>" + escapeHtml(r) + "</li>";
      });
      html += "</ul></div>";
    }

    if (d.status === "need_user_confirmation") {
      html +=
        '<div class="note-block warn"><h4>需要你确认</h4><p>当前方案略超预算上限，若你接受小幅超支可继续；否则请说明「严格不超预算」以便进一步降配。</p></div>'; // 超预算需用户表态
    }

    var alts = d.alternative_suggestions || []; // 替代建议文案
    if (alts.length) {
      html += '<div class="note-block danger"><h4>替代建议</h4><ul>'; // 危险样式
      alts.forEach(function (r) {
        html += "<li>" + escapeHtml(r) + "</li>";
      });
      html += "</ul></div>";
    }

    var md = d.recommendation_markdown || ""; // 后端渲染的长文 Markdown
    if (md) {
      html += '<h3 style="margin-top:20px;font-size:15px;">详细说明</h3>'; // 小标题
      html += renderMarkdown(md); // 转 HTML 片段
    }

    html += buildDebugHtml(d.debug_llm); // 成功态也可附带调试面板于结果底部

    el.resultInner.innerHTML = html; // 一次性写入右侧结果
  }

  // 渲染解析失败等错误态：展示 message 与替代建议、markdown、调试
  function renderFailed(payload) {
    el.clarifyWrap.classList.add("hidden"); // 隐藏追问
    el.resultWrap.classList.remove("hidden"); // 显示结果容器承载错误信息
    clearDebugHost(); // 清理追问区调试点
    var d = payload.data || {}; // 解包 data
    if (d.session_id) {
      setSessionId(d.session_id); // 错误响应也可能带 session 以便重试
    }

    var html = '<div class="note-block danger"><h4>暂无法生成闭环方案</h4>'; // 错误标题区
    html += "<p>" + escapeHtml(payload.message || "failed") + "</p>"; // 错误码/简述
    var alts = d.alternative_suggestions || []; // 若有替代说明一并列出
    if (alts.length) {
      html += "<ul>";
      alts.forEach(function (a) {
        html += "<li>" + escapeHtml(a) + "</li>";
      });
      html += "</ul>";
    }
    var md = d.recommendation_markdown || ""; // 可能仍有说明 markdown
    if (md) {
      html += renderMarkdown(md);
    }
    html += "</div>"; // 关闭 danger 容器
    html += buildDebugHtml(d.debug_llm); // 错误时也可能需要看调试
    el.resultInner.innerHTML = html; // 写入 DOM
  }

  // 表单提交：串起加载态、分支渲染、错误捕获
  async function onSubmit(e) {
    e.preventDefault(); // 阻止浏览器默认提交导致页面刷新
    var q = el.query.value.trim(); // 取用户输入并去首尾空白
    if (!q) {
      alert("请先描述你的装机需求（预算、用途、是否要显示器等）。"); // 客户端校验减少无效请求
      return; // 提前返回
    }

    el.btnSubmit.disabled = true; // 禁用按钮防连点
    el.loader.classList.add("on"); // 显示加载条（CSS 控制 on 类）
    clearDebugHost(); // 新请求前清理旧调试区

    try {
      var json = await postRecommend(q); // 等待网络与 JSON 解析
      var data = json.data || {}; // 统一解包 data

      if (json.code !== 0 && json.message === "parse_failed") {
        renderFailed(json); // 需求理解失败走失败模板
        return;
      }

      if (data.need_clarification) {
        resetSelections(); // 新一轮追问清空卡片选择
        renderClarification(data); // 展示追问 UI
        return;
      }

      if (json.message === "failed_with_alternative" || data.status === "failed_with_alternative") {
        renderSuccess(json); // 与成功共用模板展示替代方案信息
        return;
      }

      renderSuccess(json); // 默认成功路径
    } catch (err) {
      el.resultWrap.classList.remove("hidden"); // 打开结果区展示错误
      el.clarifyWrap.classList.add("hidden"); // 隐藏追问避免叠层
      el.resultInner.innerHTML =
        '<div class="note-block danger"><h4>请求出错</h4><pre style="white-space:pre-wrap;">' +
        escapeHtml(String(err)) +
        "</pre></div>"; // 展示异常栈或网络错误文本
    } finally {
      el.btnSubmit.disabled = false; // 恢复按钮无论成功失败
      el.loader.classList.remove("on"); // 隐藏加载动画
    }
  }

  el.form.addEventListener("submit", onSubmit); // 绑定主表单提交

  el.btnClearSession.addEventListener("click", function () {
    setSessionId(""); // 清除 sessionStorage 中的会话 id
    resetSelections(); // 清空卡片选择缓存
    el.clarifyWrap.classList.add("hidden"); // 收起追问
    el.resultWrap.classList.add("hidden"); // 收起结果
    el.resultInner.innerHTML = ""; // 清空结果 DOM
    el.clarifyContainer.innerHTML = ""; // 清空追问 DOM
    clearDebugHost(); // 清空调试区
  });

  renderSession(); // 首次进入页面刷新会话显示
})(); // IIFE 结束：不导出符号
