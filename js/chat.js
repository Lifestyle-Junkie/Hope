/*
  chat.js
  Welcome, text submit, marquee, audio unlock for Hope
*/
(function () {
  let audioUnlocked = false;
  let welcomePlayed = false;

  function $(id) {
    return document.getElementById(id);
  }

  function isBrowseMode() {
    const el = $("search");
    if (el) return !!el.checked;
    return !!window.HOPE_BROWSE_MODE;
  }

  function autoresize() {
    const ta = $("chat-input");
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 240) + "px";
  }
  window.autoresize = autoresize;

  function addHopeBubble(text) {
    const chatThread = $("chat-thread");
    if (!chatThread) return null;
    const aiBubble = document.createElement("div");
    aiBubble.className = "chat-bubble";
    aiBubble.innerHTML = (window.mdToHTML || ((s) => s))(text);
    chatThread.appendChild(aiBubble);
    aiBubble.scrollIntoView({ behavior: "smooth", block: "end" });
    return aiBubble;
  }
  window.addHopeBubble = addHopeBubble;

  async function playWelcome() {
    if (welcomePlayed) return;
    welcomePlayed = true;
    window.hopeIsProcessing = true;
    if (window.setStatus) window.setStatus("Welcome…", true);
    let reply = "Welcome back. Want today's briefing, or just ask me something?";
    try {
      const res = await fetch(`${window.BACKEND_URL}/welcome`, { method: "GET" });
      if (res.ok) {
        const data = await res.json();
        reply = data.reply || reply;
      }
    } catch (e) {
      console.error("Welcome error:", e);
    }
    addHopeBubble(reply);
    try {
      if (window.setStatus) window.setStatus("Speaking…", true);
      if (window.speakText) await window.speakText(reply);
    } catch (e) {
      console.error("Welcome speak error:", e);
    }
    window.hopeIsProcessing = false;
    if (window.setStatus) window.setStatus('Listening for “Hope”…');
    if (window.startWakeWordMode) window.startWakeWordMode();
  }

  function unlockAudio() {
    if (audioUnlocked) return;
    const silent = new Audio(
      "data:audio/wav;base64,UklGRigAAABXQVZFZm10IBIAAAABAAEARKwAAIhYAQACABAAAABkYXRhAgAAAAEA"
    );
    silent.volume = 0.01;
    silent
      .play()
      .then(async () => {
        audioUnlocked = true;
        console.log("Audio unlocked");
        await playWelcome();
      })
      .catch(async () => {
        audioUnlocked = true;
        await playWelcome();
      });
  }

  async function handleSubmit() {
    const ta = $("chat-input");
    const chatThread = $("chat-thread");
    if (!ta || !chatThread) return;
    const text = ta.value.trim();
    if (!text) return;
    ta.value = "";
    autoresize();

    window.HOPE_BROWSE_MODE = isBrowseMode();

    if (window.simulateChatResponse) {
      await window.simulateChatResponse(text, chatThread, 35);
      return;
    }

    const userBubble = document.createElement("div");
    userBubble.className = "chat-bubble user";
    userBubble.textContent = text;
    chatThread.appendChild(userBubble);

    const aiBubble = document.createElement("div");
    aiBubble.className = "chat-bubble";
    aiBubble.textContent = "…";
    chatThread.appendChild(aiBubble);

    try {
      const res = await fetch(`${window.BACKEND_URL}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          message: text,
          concise: !!window.CONCISE_MODE,
          browse_mode: isBrowseMode(),
        }),
      });
      const data = await res.json();
      aiBubble.innerHTML = (window.mdToHTML || ((s) => s))(
        data.reply || "No response"
      );
    } catch (e) {
      aiBubble.textContent = "Error contacting Hope";
    }
  }

  function initChat() {
    const ta = $("chat-input");
    const submitBtn = $("submitBtn");
    if (ta) {
      ["input", "change"].forEach((ev) => ta.addEventListener(ev, autoresize));
      ta.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey) {
          e.preventDefault();
          handleSubmit();
        }
      });
    }
    if (submitBtn) {
      submitBtn.addEventListener("click", handleSubmit);
    }
    document.querySelectorAll(".chat-marquee li").forEach((li) => {
      li.addEventListener("click", () => {
        if (!ta) return;
        ta.value = li.textContent;
        autoresize();
        ta.focus();
      });
    });
    document.body.addEventListener("click", unlockAudio, { once: true });
    document.body.addEventListener("touchstart", unlockAudio, { once: true });
    window.addEventListener("DOMContentLoaded", () => {
      document.body.classList.add("ready");
    });
    if (document.readyState !== "loading") {
      document.body.classList.add("ready");
    }
    console.log("[Chat] Ready");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initChat);
  } else {
    initChat();
  }
})();
