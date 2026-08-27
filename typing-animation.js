/*
typing-animation.js
Frontend chat helper
- strip mangled target=_blank debris
- live HTML preview card
- browse_mode flag
- preview card styles for Neural Orb UI
*/
let CONCISE_MODE = false;
let backendMemory = {
  last_person: null,
  topic: null
};

function setConciseMode(on) {
  CONCISE_MODE = !!on;
  console.log("[Client] CONCISE_MODE =", CONCISE_MODE);
}

function isBrowseMode() {
  const el = document.getElementById("search");
  if (el) return !!el.checked;
  return !!window.HOPE_BROWSE_MODE;
}

(function injectHopeStyles() {
  if (document.getElementById("hope-link-styles")) return;
  const style = document.createElement("style");
  style.id = "hope-link-styles";
  style.textContent = `
    .chat-bubble a,
    .chat-bubble a:link,
    .chat-bubble a:visited {
      color: #79d2ff !important;
      text-decoration: underline !important;
      pointer-events: auto !important;
      cursor: pointer !important;
      word-break: break-all;
    }
    .html-preview-card {
      margin-top: 8px;
      border: 1px solid rgba(120,200,255,0.25);
      border-radius: 12px;
      overflow: hidden;
      background: rgba(8,14,26,0.9);
    }
    .html-preview-card .hp-header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      padding: 8px 10px;
      font-size: 11px;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #bfe9ff;
      border-bottom: 1px solid rgba(120,200,255,0.15);
    }
    .html-preview-card .hp-actions button {
      margin-left: 6px;
      background: transparent;
      border: 1px solid rgba(140,210,255,0.3);
      color: #d7f3ff;
      border-radius: 999px;
      padding: 3px 8px;
      cursor: pointer;
      font-size: 11px;
    }
    .html-preview-card .hp-frame-wrap { height: 220px; background: #fff; }
    .html-preview-card .hp-frame { width: 100%; height: 220px; border: 0; }
    .html-preview-card .hp-code {
      display: none;
      margin: 0;
      padding: 10px;
      max-height: 220px;
      overflow: auto;
      font-size: 11px;
      color: #d7eef8;
      white-space: pre-wrap;
    }
    .html-preview-card.show-code .hp-frame-wrap { display: none; }
    .html-preview-card.show-code .hp-code { display: block; }
    .hp-intro { margin-bottom: 8px; }
  `;
  document.head.appendChild(style);
})();

function simulateTypingEffect(text, element, speed = 18, done) {
  element.innerHTML = "";
  let i = 0;
  const BATCH_SIZE = 3;
  const full = String(text || "");
  function step() {
    if (i < full.length) {
      const end = Math.min(i + BATCH_SIZE, full.length);
      element.textContent = full.slice(0, end);
      i = end;
      setTimeout(step, speed);
    } else {
      done && done();
    }
  }
  step();
}

function stripToPlain(s) {
  if (!s) return "";
  let text = String(s);
  text = text.replace(
    /<a\s+[^>]*href\s*=\s*["']([^"']+)["'][^>]*>([\s\S]*?)<\/a>/gi,
    (_, href, label) => {
      const cleanHref = String(href).trim().replace(/["']/g, "");
      const cleanLabel = String(label).replace(/<[^>]+>/g, "").trim();
      if (cleanLabel && cleanLabel !== cleanHref) {
        return `${cleanLabel} (${cleanHref})`;
      }
      return cleanHref;
    }
  );
  text = text.replace(/["']?\s*target\s*=\s*["']?_blank["']?\s*rel\s*=\s*["'][^"']*["']\s*>/gi, " ");
  text = text.replace(/(https?:\/\/[^\s"'<>]+)["']?\s+([A-Za-z0-9][A-Za-z0-9._-]*)/g, (m, url, maybeLabel) => `${maybeLabel} (${url})`);
  text = text.replace(/(https?:\/\/[^\s]+?)["']+/g, "$1");
  return text
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .replace(/&#39;/g, "'")
    .replace(/\s+/g, " ")
    .trim();
}

function plainForTyping(s) {
  if (!s) return "";
  return stripToPlain(s)
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1 ($2)")
    .replace(/\n\n/g, "\n")
    .replace(/\s+/g, " ")
    .trim();
}

function mdToHTML(s) {
  if (!s) return "";
  let text = stripToPlain(s);
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");
  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
  html = html.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/gi,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );
  html = html.replace(/https?:\/\/[^\s<]+/gi, (match, offset, full) => {
    const before = full.slice(Math.max(0, offset - 12), offset).toLowerCase();
    if (before.includes('href="') || before.includes("href='") || before.includes("href=")) return match;
    const trailing = match.match(/[.,!?);:"'\]]+$/);
    let clean = trailing ? match.slice(0, -trailing[0].length) : match;
    clean = clean.replace(/["']/g, "");
    const end = trailing ? trailing[0].replace(/["']/g, "") : "";
    return `<a href="${clean}" target="_blank" rel="noopener noreferrer">${clean}</a>${end}`;
  });
  html = html.replace(
    /\b((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|co|app|ai|gg|tv|me|us|uk|ca|de|fr|nz|info|biz))\b/gi,
    (domain, _1, offset, full) => {
      const before = full.slice(Math.max(0, offset - 15), offset).toLowerCase();
      if (before.includes("href=") || before.includes("://") || before.includes("<a ")) return domain;
      return `<a href="https://${domain}" target="_blank" rel="noopener noreferrer">${domain}</a>`;
    }
  );
  html = html.replace(/\n\n/g, "<br><br>");
  html = html.replace(/\n/g, "<br>");
  return html;
}

function renderReplyHTML(element, reply) {
  element.innerHTML = mdToHTML(reply);
  const hasAnchor = element.querySelector("a");
  if (!hasAnchor) {
    const raw = element.textContent || "";
    if (/https?:\/\//i.test(raw) || /\b[\w-]+\.(com|net|org|io)\b/i.test(raw)) {
      element.innerHTML = mdToHTML(raw);
    }
  }
}

function extractHtmlFence(text) {
  if (!text) return null;
  const raw = String(text);
  const fence = raw.match(/```html\s*([\s\S]*?)```/i);
  if (fence) {
    return { html: fence[1].trim(), intro: raw.slice(0, fence.index).trim(), rest: raw.slice(fence.index + fence[0].length).trim() };
  }
  const anyFence = raw.match(/```[a-zA-Z]*\s*([\s\S]*?)```/);
  if (anyFence && /<!DOCTYPE\s+html|<html[\s>]/i.test(anyFence[1])) {
    return { html: anyFence[1].trim(), intro: raw.slice(0, anyFence.index).trim(), rest: raw.slice(anyFence.index + anyFence[0].length).trim() };
  }
  if (/<!DOCTYPE\s+html|<html[\s>]/i.test(raw)) {
    return { html: raw.trim(), intro: "", rest: "" };
  }
  return null;
}

function renderHtmlPreviewCard(container, htmlSource, introText) {
  container.innerHTML = "";
  container.style.whiteSpace = "normal";
  if (introText) {
    const intro = document.createElement("div");
    intro.className = "hp-intro";
    intro.textContent = introText;
    container.appendChild(intro);
  }
  const card = document.createElement("div");
  card.className = "html-preview-card";
  const header = document.createElement("div");
  header.className = "hp-header";
  const title = document.createElement("span");
  title.textContent = "HTML";
  header.appendChild(title);
  const actions = document.createElement("div");
  actions.className = "hp-actions";
  const btnPreview = document.createElement("button");
  btnPreview.type = "button";
  btnPreview.textContent = "Preview";
  const btnCode = document.createElement("button");
  btnCode.type = "button";
  btnCode.textContent = "Code";
  const btnCopy = document.createElement("button");
  btnCopy.type = "button";
  btnCopy.textContent = "Copy";
  actions.appendChild(btnPreview);
  actions.appendChild(btnCode);
  actions.appendChild(btnCopy);
  header.appendChild(actions);
  card.appendChild(header);
  const frameWrap = document.createElement("div");
  frameWrap.className = "hp-frame-wrap";
  const iframe = document.createElement("iframe");
  iframe.className = "hp-frame";
  iframe.setAttribute("sandbox", "allow-scripts allow-same-origin");
  iframe.title = "HTML preview";
  iframe.srcdoc = htmlSource;
  frameWrap.appendChild(iframe);
  card.appendChild(frameWrap);
  const pre = document.createElement("pre");
  pre.className = "hp-code";
  pre.textContent = htmlSource;
  card.appendChild(pre);
  btnPreview.addEventListener("click", () => card.classList.remove("show-code"));
  btnCode.addEventListener("click", () => card.classList.add("show-code"));
  btnCopy.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(htmlSource);
      btnCopy.textContent = "Copied";
      setTimeout(() => { btnCopy.textContent = "Copy"; }, 1200);
    } catch (_) {
      btnCopy.textContent = "Failed";
      setTimeout(() => { btnCopy.textContent = "Copy"; }, 1200);
    }
  });
  container.appendChild(card);
  return card;
}

async function simulateChatResponse(userText, chatThread, speed = 22, imageData = null) {
  const userBubble = document.createElement("div");
  userBubble.className = "chat-bubble user";
  userBubble.setAttribute("role", "user");
  userBubble.textContent = userText || "[image]";
  let validImageData = imageData;
  if (imageData) {
    if (typeof imageData === "string" && (imageData.startsWith("data:image/") || imageData.startsWith("blob:"))) {
      const img = new Image();
      img.onload = () => {
        if (img.naturalWidth > 0) {
          const imgEl = document.createElement("img");
          imgEl.src = imageData;
          imgEl.alt = "User image";
          imgEl.style.maxWidth = "200px";
          userBubble.appendChild(imgEl);
        }
      };
      img.onerror = () => console.warn("[Client] Invalid image data");
      img.src = imageData;
    } else {
      validImageData = null;
    }
  }
  chatThread.appendChild(userBubble);
  userBubble.scrollIntoView({ behavior: "smooth", block: "end" });

  const aiBubble = document.createElement("div");
  aiBubble.className = "chat-bubble";
  aiBubble.setAttribute("aria-live", "polite");
  aiBubble.innerHTML = "…";
  chatThread.appendChild(aiBubble);
  aiBubble.scrollIntoView({ behavior: "smooth", block: "end" });

  const payload = {
    message: userText,
    concise: CONCISE_MODE,
    browse_mode: isBrowseMode()
  };
  if (validImageData) payload.image = validImageData;

  let data;
  try {
    const res = await fetch(`${window.BACKEND_URL}/ask`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload)
    });
    if (!res.ok) {
      const errorData = await res.json().catch(() => ({}));
      throw new Error(errorData.error || `HTTP ${res.status}`);
    }
    data = await res.json();
  } catch (e) {
    aiBubble.textContent = e.message || "Network error.";
    return;
  }

  let reply = data.reply || data.liveweb_analyzed || "No response available.";
  if (userText && reply.includes(userText)) {
    reply = reply.replace(userText, "").trim() || data.liveweb_analyzed || "Sorry, I couldn't process that.";
  }

  const memory = data.memory || {};
  if (memory.last_person) backendMemory.last_person = memory.last_person;
  if (memory.topic) backendMemory.topic = memory.topic;
  if (data.context_used) {
    const ctxBadge = document.createElement("div");
    ctxBadge.className = "chat-bubble context-badge";
    ctxBadge.style.opacity = "0.7";
    ctxBadge.style.fontSize = "0.75rem";
    ctxBadge.innerHTML = `<em>Context reused: ${backendMemory.last_person || backendMemory.topic || "previous topic"}</em>`;
    chatThread.insertBefore(ctxBadge, aiBubble);
  }

  const htmlPart = extractHtmlFence(reply);
  if (htmlPart && htmlPart.html) {
    renderHtmlPreviewCard(aiBubble, htmlPart.html, htmlPart.intro || "Here's a preview:");
    if (htmlPart.rest) {
      const extra = document.createElement("div");
      extra.style.marginTop = "0.5rem";
      extra.innerHTML = mdToHTML(htmlPart.rest);
      aiBubble.appendChild(extra);
    }
  } else {
    const typingText = plainForTyping(reply);
    simulateTypingEffect(typingText, aiBubble, speed, () => {
      renderReplyHTML(aiBubble, reply);
      aiBubble.scrollIntoView({ behavior: "smooth", block: "end" });
    });
  }
}

window.simulateChatResponse = simulateChatResponse;
window.setConciseMode = setConciseMode;
window.extractHtmlFence = extractHtmlFence;
window.renderHtmlPreviewCard = renderHtmlPreviewCard;
