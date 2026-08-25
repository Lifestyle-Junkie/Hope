/*
  voice.js
  Wake word + mic + speech recognition + TTS for Hope
  Continuous conversation: while mic is checked, keep listening after Hope speaks
*/
(function () {
  let recognition = null;
  let mode = "wake"; // "wake" | "command"
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

  function isMicOn() {
    const { micCheckbox } = getEls();
    return !!(micCheckbox && micCheckbox.checked);
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

  // After Hope finishes: keep talking if mic is on, otherwise wake word
  function resumeAfterHope() {
    if (isMicOn()) {
      // Continuous conversation mode
      setTimeout(() => startCommandMode(), 350);
    } else {
      startWakeWordMode();
    }
  }

  function safeRestartWake() {
    if (mode !== "wake" || window.hopeIsProcessing) return;
    if (isMicOn()) {
      // Mic was turned on — stay in command mode
      startCommandMode();
      return;
    }
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
    if (isMicOn()) {
      // Don't fall back to wake while user wants continuous talk
      startCommandMode();
      return;
    }

    mode = "wake";
    setStatus('Listening for “Hope”…');
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
    const { micLabel, ta, micCheckbox } = getEls();
    if (micLabel) micLabel.classList.add("listening-active");
    // Keep checkbox in sync when entering command from wake word
    if (micCheckbox && !micCheckbox.checked) {
      // optional: leave unchecked for pure wake-word one-shots
    }
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
        resumeAfterHope();
      }
    };

    recognition.onerror = (event) => {
      console.log("[Command] Error:", event.error);
      if (micLabel) micLabel.classList.remove("listening-active");
      // Keep listening if mic is still on
      if (isMicOn() && !window.hopeIsProcessing) {
        setTimeout(() => startCommandMode(), 500);
      } else {
        setTimeout(() => startWakeWordMode(), 600);
      }
    };

    recognition.onend = () => {
      if (micLabel) micLabel.classList.remove("listening-active");
      // If still in command mode and not processing, and mic is on → listen again
      if (mode === "command" && !window.hopeIsProcessing) {
        if (isMicOn()) {
          setTimeout(() => startCommandMode(), 400);
        } else {
          setTimeout(() => startWakeWordMode(), 650);
        }
      }
    };

    try {
      recognition.start();
    } catch (e) {
      console.warn("Command start failed:", e);
      if (isMicOn()) {
        setTimeout(() => startCommandMode(), 700);
      } else {
        startWakeWordMode();
      }
    }
  }
  window.startCommandMode = startCommandMode;

  async function handleVoiceCommand(text) {
    if (window.hopeIsProcessing) return;
    window.hopeIsProcessing = true;
    setStatus("Thinking…");

    const { chatThread, micLabel } = getEls();
    if (micLabel) micLabel.classList.remove("listening-active");

    if (!chatThread) {
      window.hopeIsProcessing = false;
      resumeAfterHope();
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
    // KEY CHANGE: continuous if mic is on
    resumeAfterHope();
  }
  window.handleVoiceCommand = handleVoiceCommand;

  function wireMic() {
    const { micCheckbox } = getEls();
    if (!micCheckbox) return;

    micCheckbox.addEventListener("change", () => {
      if (micCheckbox.checked) {
        // Continuous conversation ON
        startCommandMode();
      } else {
        // Continuous OFF → back to wake word only
        mode = "wake";
        stopRecognition();
        startWakeWordMode();
      }
    });
  }

  function initVoice() {
    wireMic();
    console.log("[Voice] Ready (continuous mic supported)");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initVoice);
  } else {
    initVoice();
  }
})();
