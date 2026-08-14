/*
typing-animation.js
Frontend chat helper with:
- Streaming type effect (simple incremental reveal, batched for perf)
- Context awareness visualization (shows when backend reused context)
- Optional concise mode toggle
- Basic memory sync from backend (backend is authoritative)
- Configurable backend URL and improved error/image handling
- Fix for echo bug and safety note rendering
*/

let CONCISE_MODE = false;

// Local mirrors of backend memory (for UI only)
let backendMemory = {
  last_person: null,
  topic: null
};

// Use var so it doesn't conflict with the const in Index.html
var BACKEND_URL = window.BACKEND_URL || 'https://hope-production-7e9d.up.railway.app';

function setConciseMode(on) {
  CONCISE_MODE = !!on;
  console.log("[Client] CONCISE_MODE =", CONCISE_MODE);
}

function simulateTypingEffect(text, element, speed = 18, done) {
  element.innerHTML = "";
  let i = 0;
  const BATCH_SIZE = 3;
  function step() {
    if (i <= text.length) {
      const end = Math.min(i + BATCH_SIZE, text.length);
      element.innerHTML = text.slice(0, end);
      i = end;
      setTimeout(step, speed);
    } else {
      done && done();
    }
  }
  step();
}

function mdToHTML(s) {
  if (!s) return "";
  let html = s
    .replace(/\*\*(.*?)\*\*/g, "<strong>$1</strong>")
    .replace(/`([^`]+)`/g, "<code>$1</code>")
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>');
  html = html.replace(/\n\n/g, '<br><br>');
  return html;
}

async function simulateChatResponse(userText, chatThread, speed = 22, imageData = null) {
  // User bubble
  const userBubble = document.createElement("div");
  userBubble.className = "chat-bubble user";
  userBubble.setAttribute("role", "user");
  userBubble.textContent = userText || "[image]";
  let validImageData = imageData;
  if (imageData) {
    if (typeof imageData === 'string' && (imageData.startsWith('data:image/') || imageData.startsWith('blob:'))) {
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
    const res = await fetch(`${BACKEND_URL}/ask`, {
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
  if (reply.includes(userText)) {
    reply = reply.replace(userText, '').trim() || data.liveweb_analyzed || "Sorry, I couldn't process that.";
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
    ctxBadge.innerHTML = `<em>Context reused: ${backendMemory.last_person || backendMemory.topic || "previous topic"}</em>`;
    chatThread.insertBefore(ctxBadge, aiBubble);
  }

  simulateTypingEffect(mdToHTML(reply), aiBubble, speed, () => {
    aiBubble.scrollIntoView({ behavior: "smooth", block: "end" });
  });

  if (data.liveweb_analyzed &&
      data.liveweb_analyzed.startsWith("**Note:**") &&
      (reply === "It is not specified." || reply === "No data available.")) {
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
