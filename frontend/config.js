/**
 * 前后端分离 — 前端运行时配置（本文件与 index.html、app.js 同目录部署）。
 *
 * 修改说明：
 * - 将 window.PC_GUIDE_API_BASE 设为后端 FastAPI 的根地址（无尾斜杠），例如 http://127.0.0.1:8000
 * - 浏览器会从此地址发起 fetch；后端须在 PC_GUIDE_CORS_ORIGINS 中包含本页 Origin（协议+域名+端口）
 */
(function () {
  // 若外层已通过内联脚本或部署脚本注入，则保留注入值；否则使用本地默认后端端口 8000
  if (typeof window.PC_GUIDE_API_BASE !== "string" || !window.PC_GUIDE_API_BASE) {
    window.PC_GUIDE_API_BASE = "http://127.0.0.1:8000"; // 本地 uvicorn 默认监听地址（与 README 一致）
  }

  /**
   * 规范化 API 根：去掉末尾 /，避免与路径拼接出现 //
   * @returns {string} 基址字符串，可能为空（空则 app.js 会提示配置）
   */
  function normalizedBase() {
    return String(window.PC_GUIDE_API_BASE || "").replace(/\/+$/, ""); // 正则：一个或多个尾部斜杠
  }

  /**
   * 在 DOM 就绪后把顶部导航「API 文档」「服务状态」指到后端同源路径（跨端口仍属跨域，但链接可新开页）
   */
  function wireHeaderLinks() {
    var base = normalizedBase(); // 取当前配置的 API 根
    if (!base) {
      return; // 未配置则不改写，避免生成无效 javascript:void 链接
    }
    var docs = document.getElementById("link-docs"); // API 文档锚点（OpenAPI Swagger UI）
    var health = document.getElementById("link-health"); // 健康检查锚点
    if (docs) {
      docs.href = base + "/docs"; // FastAPI 自动挂载的 Swagger 路径
    }
    if (health) {
      health.href = base + "/health"; // 与后端 health() 对应
    }
  }

  // DOMContentLoaded：保证 getElementById 能取到 index.html 中的元素
  document.addEventListener("DOMContentLoaded", wireHeaderLinks);
})();
