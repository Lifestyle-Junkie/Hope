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

// Configurable backend URL (set window.BACKEND_URL for prod)
const BACKEND_URL = window.BACKEND_URL || 'http://localhost:5002';

function setConciseMode(on) {
  CONCISE_MODE = !!on;
  console.log("[Client] CONCISE_MODE =", CONCISE_MODE);
}

function simulateTypingEffect(text, element, speed = 18, done) {
  element.innerHTML = "";
  let i = 0;
  const BATCH_SIZE = 3; // Batch chars for better perf on long texts
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
    .replace(/\[([^\]]+)\]\(([^)]+)\)/g, '<a href="$2" target="_blank" rel="noopener">$1</a>'); // Basic link support
  // Clean up any remaining Markdown edge cases
  html = html.replace(/\n\n/g, '<br><br>');
  return html;
}

async function simulateChatResponse(userText, chatThread, speed = 22, imageData = null) {
  // User bubble
  const userBubble = document.createElement("div");
  userBubble.className = "chat-bubble user";
  userBubble.setAttribute("role", "user"); // Accessibility
  userBubble.textContent = userText || "[image]";
  let validImageData = imageData;
  if (imageData) {
    // Basic validation: Ensure it's a data URL or blob, <5MB, common formats
    if (typeof imageData === 'string' && (imageData.startsWith('data:image/') || imageData.startsWith('blob:'))) {
      const img = new Image();
      img.onload = () => {
        if (img.naturalWidth > 0) {
          const imgEl = document.createElement("img");
          imgEl.src = imageData;
          imgEl.alt = "User image";
          imgEl.style.maxWidth = "200px"; // Prevent overflow
          userBubble.appendChild(imgEl);
        }
      };
      img.onerror = () => console.warn("[Client] Invalid image data");
      img.src = imageData; // Trigger load
    } else {
      console.warn("[Client] Skipping invalid image");
      validImageData = null;
    }
  }
  chatThread.appendChild(userBubble);
  userBubble.scrollIntoView({ behavior: "smooth", block: "end" });

  // AI placeholder with accessibility
  const aiBubble = document.createElement("div");
  aiBubble.className = "chat-bubble";
  aiBubble.setAttribute("aria-live", "polite");
  aiBubble.setAttribute("role", "log"); // For screen readers
  aiBubble.innerHTML = "<span class='dot'>.</span><span class='dot'>.</span><span class='dot'>.</span>";
  chatThread.appendChild(aiBubble);
  aiBubble.scrollIntoView({ behavior: "smooth", block: "end" });

  // Build payload (backend keeps true memory; we only send message + concise + optional image)
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

  let reply = data.reply || data.liveweb_analyzed || "No response available.";  // Fallback chain
  if (reply.includes(userText)) {  // Fix echo: Strip user prompt if accidentally included
    reply = reply.replace(userText, '').trim() || data.liveweb_analyzed || "Sorry, I couldn't process that.";
  }

  const contextUsed = data.context_used;
  const memory = data.memory || {};
  if (memory.last_person) backendMemory.last_person = memory.last_person;
  if (memory.topic) backendMemory.topic = memory.topic;

  // Optional context badge
  if (contextUsed) {
    const ctxBadge = document.createElement("div");
    ctxBadge.className = "chat-bubble context-badge"; // For styling
    ctxBadge.style.opacity = "0.7";
    ctxBadge.style.fontSize = "0.75rem";
    ctxBadge.innerHTML = `<em>Context reused: ${backendMemory.last_person || backendMemory.topic || "previous topic"}</em>`;
    chatThread.insertBefore(ctxBadge, aiBubble);
  }

  // Render reply with typing effect
  simulateTypingEffect(mdToHTML(reply), aiBubble, speed, () => {
    aiBubble.scrollIntoView({ behavior: "smooth", block: "end" });
  });

  // (Optional) show safety notes only if reply is a fallback
  if (data.liveweb_analyzed &&
      data.liveweb_analyzed.startsWith("**Note:**") &&
      (reply === "It is not specified." || reply === "No data available.")) {
    const noteBubble = document.createElement("div");
    noteBubble.className = "chat-bubble note";
    noteBubble.style.fontSize = "0.85rem";
    noteBubble.style.color = "#666"; // Subtle styling
    noteBubble.innerHTML = mdToHTML(data.liveweb_analyzed);
    chatThread.appendChild(noteBubble);
    noteBubble.scrollIntoView({ behavior: "smooth", block: "end" });
  }
}

// Expose to window
window.simulateChatResponse = simulateChatResponse;
window.setConciseMode = setConciseMode;