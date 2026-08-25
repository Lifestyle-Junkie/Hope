/*
  voice.js
  Wake word + mic + speech recognition + TTS for Hope
*/
(function () {
  let recognition = null;
  let mode = "wake";
  let restartAttempts = 0;
  const MAX_RESTART_ATTEMPTS = 10;

  // Shared so welcome / chat can coordinate
  window.hopeIsProcessing = false;

  function $(id) {
    return document.getElementById(id);
  }

  function getEls() {
    return {
      ta: $("chat-input"),
      chatThread: $("chat-thread"),
      micCheckbox: $("mic"),
      micLabel: document.querySelector('label[for="mic"]'),
      wakeStatus: $("wake-status"),
    };
  }

  function setStatus(text, active = false) {
    const { wakeStatus } = getEls();
    if (!wakeStatus) return;
    wakeStatus.textContent = text;
    wakeStatus.classList.toggle("active", active);
  }

  window.setStatus = setStatus;

  function autoresize() {
    const { ta } = getEls();
    if (!ta) return;
    ta.style.height = "auto";
    ta.style.height = Math.min(ta.scrollHeight, 240) + "px";
  }

  async function speakText(text) {
    const speakRes = await fetch(`${window.BACKEND_URL}/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!speakRes.ok) throw new Error("Speak failed");
    const audioBlob = await speakRes.blob();
    const audioUrl = URL.createObjectURL(audioBlob);
    const audio = new Audio(audioUrl);
    await new Promise((resolve, reject) => {
      audio.onended = () => {
        URL.revokeObjectURL(audioUrl);
        resolve();
      };
      audio.onerror = reject;
      audio.play().catch(reject);
    });
  }

  window.speakText = speakText;

  function createRecognition() {
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      setStatus("Speech not supported – use Chrome");
      return null;
    }
    const recog = new SpeechRecognition();
    recog.continuous = false;
    recog.interimResults = false;
    recog.lang = "en-US";
    recog.maxAlternatives = 1;
    return recog;
  }

  function stopRecognition() {
    if (!recognition) return;
    try {
      recognition.onend = null;
      recognition.onerror = null;
      recognition.onresult = null;
      recognition.abort();
    } catch (e) {}
    recognition = null;
  }

  function safeRestartWake() {
    if (mode !== "wake" || window.hopeIsProcessing) return;
    restartAttempts++;
    if (restartAttempts > MAX_RESTART_ATTEMPTS) {
      console.log("[Wake] Cooling down...");
      setStatus("Wake word paused – click mic or say “Hope” again");
      setTimeout(() => {
        restartAttempts = 0;
        startWakeWordMode();
      }, 3500);
      return;
    }
    startWakeWordMode();
  }

  function startWakeWordMode() {
    if (window.hopeIsProcessing) return;
    mode = "wake";
    setStatus("Listening for “Hope”…");
    const { micLabel } = getEls();
    if (micLabel) micLabel.classList.remove("listening-active");

    stopRecognition();
    recognition = createRecognition();
    if (!recognition) return;

    recognition.onresult = (event) => {
      const transcript = event.results[0][0].transcript.toLowerCase().trim();
      console.log("[Wake] Heard:", transcript);
      if (
        transcript.includes("hope") ||
        transcript.includes("hey hope") ||
        transcript.includes("hi hope") ||
        transcript.includes("okay hope") ||
        transcript.includes("yo hope") ||
        transcript.includes("hey ho")
      ) {
        console.log("[Wake] Wake word detected!");
        restartAttempts = 0;
        startCommandMode();
      } else {
        setTimeout(() => {
          if (mode === "wake" && !window.hopeIsProcessing) safeRestartWake();
        }, 280);
      }
    };

    recognition.onerror = (event) => {
      console.log("[Wake] Error:", event.error);
      if (mode === "wake" && !window.hopeIsProcessing) {
        const delay =
          event.error === "no-speech" || event.error === "aborted" ? 450 : 1100;
        setTimeout(() => safeRestartWake(), delay);
      }
    };

    recognition.onend = () => {
      if (mode === "wake" && !window.hopeIsProcessing) {
        setTimeout(() => safeRestartWake(), 350);
      }
    };

    try {
      recognition.start();
    } catch (e) {
      console.warn("Wake start failed:", e);
      setTimeout(() => safeRestartWake(), 900);
    }
  }

  window.startWakeWordMode = startWakeWordMode;

  function startCommandMode() {
    if (window.hopeIsProcessing) return;
    mode = "command";
    setStatus("Listening… speak now", true);
    const { micLabel, ta } = getEls();
    if (micLabel) micLabel.classList.add("listening-active");
    restartAttempts = 0;

    stopRecognition();
    recognition = createRecognition();
    if (!recognition) return;

    recognition.onresult = async (event) => {
      const transcript = event.results[0][0].transcript.trim();
      console.log("[Command] Heard:", transcript);
      if (transcript) {
        if (ta) {
          ta.value = transcript;
          autoresize();
        }
        await handleVoiceCommand(transcript);
      } else {
        startWakeWordMode();
      }
    };

    recognition.onerror = (event) => {
      console.log("[Command] Error:", event.error);
      if (micLabel) micLabel.classList.remove("listening-active");
      setTimeout(() => startWakeWordMode(), 600);
    };

    recognition.onend = () => {
      if (micLabel) micLabel.classList.remove("listening-active");
      if (mode === "command" && !window.hopeIsProcessing) {
        setTimeout(() => startWakeWordMode(), 650);
      }
    };

    try {
      recognition.start();
    } catch (e) {
      console.warn("Command start failed:", e);
      startWakeWordMode();
    }
  }

  window.startCommandMode = startCommandMode;

  async function handleVoiceCommand(text) {
    if (window.hopeIsProcessing) return;
    window.hopeIsProcessing = true;
    setStatus("Thinking…");

    const { chatThread } = getEls();
    if (!chatThread) {
      window.hopeIsProcessing = false;
      startWakeWordMode();
      return;
    }

    const userBubble = document.createElement("div");
    userBubble.className = "chat-bubble user";
    userBubble.textContent = text;
    chatThread.appendChild(userBubble);
    userBubble.scrollIntoView({ behavior: "smooth", block: "end" });

    const aiBubble = document.createElement("div");
    aiBubble.className = "chat-bubble";
    aiBubble.innerHTML = "…";
    chatThread.appendChild(aiBubble);
    aiBubble.scrollIntoView({ behavior: "smooth", block: "end" });

    let reply = "No response available.";
    try {
      const res = await fetch(`${window.BACKEND_URL}/ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text }),
      });
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const data = await res.json();
      reply = data.reply || data.liveweb_analyzed || "No response available.";
    } catch (e) {
      reply = `⚠️ ${e.message || "Network error"}`;
      console.error(e);
    }

    const htmlFn = window.mdToHTML || ((s) => s);
    aiBubble.innerHTML = htmlFn(reply);
    aiBubble.scrollIntoView({ behavior: "smooth", block: "end" });

    try {
      setStatus("Speaking…", true);
      await speakText(reply);
    } catch (err) {
      console.error("TTS error:", err);
    }

    window.hopeIsProcessing = false;
    startWakeWordMode();
  }

  window.handleVoiceCommand = handleVoiceCommand;

  function wireMic() {
    const { micCheckbox } = getEls();
    if (!micCheckbox) return;
    micCheckbox.addEventListener("change", () => {
      if (micCheckbox.checked) {
        startCommandMode();
      } else {
        startWakeWordMode();
      }
    });
  }

  function initVoice() {
    wireMic();
    console.log("[Voice] Ready");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initVoice);
  } else {
    initVoice();
  }
})();
