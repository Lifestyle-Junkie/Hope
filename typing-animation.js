/*
typing-animation.js
Frontend chat helper with:
- Streaming type effect (simple incremental reveal, batched for perf)
- Context awareness visualization (shows when backend reused context)
- Optional concise mode toggle
- Basic memory sync from backend (backend is authoritative)
- Configurable backend URL and improved error/image handling
- Fix for echo bug and safety note rendering
- Auto-link bare URLs, markdown links, and plain domains (clickable)
- FIXED: typing loop completes so links become clickable
- FIXED: strip existing HTML before linkifying (stops mangled welcome links)
*/

let CONCISE_MODE = false;

// Local mirrors of backend memory (for UI only)
let backendMemory = {
  last_person: null,
  topic: null
};

// Do NOT declare BACKEND_URL here — Index.html already sets it

function setConciseMode(on) {
  CONCISE_MODE = !!on;
  console.log("[Client] CONCISE_MODE =", CONCISE_MODE);
}

// Inject link styles once so anchors are visibly clickable
(function injectLinkStyles() {
  if (document.getElementById("hope-link-styles")) return;
  const style = document.createElement("style");
  style.id = "hope-link-styles";
  style.textContent = `
    .chat-bubble a,
    .chat-bubble a:link,
    .chat-bubble a:visited {
      color: #00ffd5 !important;
      text-decoration: underline !important;
      pointer-events: auto !important;
      cursor: pointer !important;
      word-break: break-all;
      position: relative;
      z-index: 5;
    }
    .chat-bubble a:hover {
      opacity: 0.85;
    }
  `;
  document.head.appendChild(style);
})();

function simulateTypingEffect(text, element, speed = 18, done) {
  element.innerHTML = "";
  let i = 0;
  const BATCH_SIZE = 3;
  const full = String(text || "");

  function step() {
    // FIXED: use < not <= so the loop actually ends
    if (i < full.length) {
      const end = Math.min(i + BATCH_SIZE, full.length);
      // textContent while typing so partial tags never break
      element.textContent = full.slice(0, end);
      i = end;
      setTimeout(step, speed);
    } else {
      // Typing finished — inject real HTML (clickable links)
      done && done();
    }
  }
  step();
}

function plainForTyping(s) {
  if (!s) return "";
  // Strip HTML if memory/backend ever stored anchors
  let t = String(s)
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"');

  return t
    .replace(/\*\*(.*?)\*\*/g, "$1")
    .replace(/`([^`]+)`/g, "$1")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, "$1 ($2)")
    .replace(/\n\n/g, "\n")
    .trim();
}

function mdToHTML(s) {
  if (!s) return "";

  // Strip any existing HTML tags so we never double-process anchors
  // (this fixes the mangled welcome: ...https://rainbet.com" target="_blank"...)
  let text = String(s)
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/p>/gi, "\n")
    .replace(/<[^>]+>/g, "")
    .replace(/&nbsp;/g, " ")
    .replace(/&amp;/g, "&")
    .replace(/&lt;/g, "<")
    .replace(/&gt;/g, ">")
    .replace(/&quot;/g, '"')
    .trim();

  // Escape
  let html = text
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;");

  // Bold
  html = html.replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>");

  // Inline code
  html = html.replace(/`([^`]+)`/g, "<code>$1</code>");

  // Markdown links [label](https://...)
  html = html.replace(
    /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/gi,
    '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>'
  );

  // Bare full URLs: https://rainbet.com/
  html = html.replace(/https?:\/\/[^\s<]+/gi, (match) => {
    const trailing = match.match(/[.,!?);:"']+$/);
    const clean = trailing ? match.slice(0, -trailing[0].length) : match;
    const end = trailing ? trailing[0] : "";
    return `<a href="${clean}" target="_blank" rel="noopener noreferrer">${clean}</a>${end}`;
  });

  // Plain domains: rainbet.com / youtube.com
  html = html.replace(
    /\b((?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+(?:com|net|org|io|co|app|ai|gg|tv|me|us|uk|ca|de|fr|nz|info|biz))\b/gi,
    (domain, _1, offset, full) => {
      const before = full.slice(Math.max(0, offset - 15), offset).toLowerCase();
      if (
        before.includes("href=") ||
        before.includes("://") ||
        before.includes("<a ")
      ) {
        return domain;
      }
      return `<a href="https://${domain}" target="_blank" rel="noopener noreferrer">${domain}</a>`;
    }
  );

  // Line breaks
  html = html.replace(/\n\n/g, "<br><br>");
  html = html.replace(/\n/g, "<br>");
  return html;
}

function renderReplyHTML(element, reply) {
  element.innerHTML = mdToHTML(reply);

  // Safety: if somehow still plain text with a URL, force-link it
  const hasAnchor = element.querySelector("a");
  if (!hasAnchor) {
    const raw = element.textContent || "";
    if (/https?:\/\//i.test(raw) || /\b[\w-]+\.(com|net|org|io)\b/i.test(raw)) {
      element.innerHTML = mdToHTML(raw);
    }
  }
}

async function simulateChatResponse(userText, chatThread, speed = 22, imageData = null) {
  // User bubble
  const userBubble = document.createElement("div");
  userBubble.className = "chat-bubble user";
  userBubble.setAttribute("role", "user");
  userBubble.textContent = userText || "[image]";

  let validImageData = imageData;
  if (imageData) {
    if (
      typeof imageData === "string" &&
      (imageData.startsWith("data:image/") || imageData.startsWith("blob:"))
    ) {
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
      console.warn("[Client] Skipping invalid image");
      validImageData = null;
    }
  }

  chatThread.appendChild(userBubble);
  userBubble.scrollIntoView({ behavior: "smooth", block: "end" });

  // AI placeholder
  const aiBubble = document.createElement("div");
  aiBubble.className = "chat-bubble";
  aiBubble.setAttribute("aria-live", "polite");
  aiBubble.setAttribute("role", "log");
  aiBubble.innerHTML = "<span class='dot'>.</span><span class='dot'>.</span><span class='dot'>.</span>";
  chatThread.appendChild(aiBubble);
  aiBubble.scrollIntoView({ behavior: "smooth", block: "end" });

  const payload = {
    message: userText,
    concise: CONCISE_MODE
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
    aiBubble.innerHTML = `⚠️ ${e.message || "Network error. Please try again."}`;
    console.error("[Client] Fetch error:", e);
    return;
  }

  let reply = data.reply || data.liveweb_analyzed || "No response available.";

  // Avoid echoing the user's exact message back as the whole reply
  if (userText && reply.includes(userText)) {
    reply =
      reply.replace(userText, "").trim() ||
      data.liveweb_analyzed ||
      "Sorry, I couldn't process that.";
  }

  const contextUsed = data.context_used;
  const memory = data.memory || {};
  if (memory.last_person) backendMemory.last_person = memory.last_person;
  if (memory.topic) backendMemory.topic = memory.topic;

  if (contextUsed) {
    const ctxBadge = document.createElement("div");
    ctxBadge.className = "chat-bubble context-badge";
    ctxBadge.style.opacity = "0.7";
    ctxBadge.style.fontSize = "0.75rem";
    ctxBadge.innerHTML = `<em>Context reused: ${
      backendMemory.last_person || backendMemory.topic || "previous topic"
    }</em>`;
    chatThread.insertBefore(ctxBadge, aiBubble);
  }

  // Type plain text, then swap in real clickable HTML
  const typingText = plainForTyping(reply);
  simulateTypingEffect(typingText, aiBubble, speed, () => {
    renderReplyHTML(aiBubble, reply);
    aiBubble.scrollIntoView({ behavior: "smooth", block: "end" });
  });

  if (
    data.liveweb_analyzed &&
    data.liveweb_analyzed.startsWith("**Note:**") &&
    (reply === "It is not specified." || reply === "No data available.")
  ) {
    const noteBubble = document.createElement("div");
    noteBubble.className = "chat-bubble note";
    noteBubble.style.fontSize = "0.85rem";
    noteBubble.style.color = "#666";
    noteBubble.innerHTML = mdToHTML(data.liveweb_analyzed);
    chatThread.appendChild(noteBubble);
    noteBubble.scrollIntoView({ behavior: "smooth", block: "end" });
  }
}

// Expose to window
window.simulateChatResponse = simulateChatResponse;
window.setConciseMode = setConciseMode;
window.mdToHTML = mdToHTML;
