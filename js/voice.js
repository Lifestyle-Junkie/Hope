/*
  voice.js
  Wake word + mic + speech recognition + TTS for Hope
  Continuous conversation + barge-in (interrupt Hope while she speaks)
*/
(function () {
  let recognition = null;
  let interruptRecognition = null;
  let mode = "wake"; // "wake" | "command"
  let restartAttempts = 0;
  const MAX_RESTART_ATTEMPTS = 10;

  let currentAudio = null;
  let isSpeaking = false;
  let interruptEnabled = false;
  let spokenTextForFilter = "";

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

  function stopSpeaking() {
    interruptEnabled = false;
    isSpeaking = false;
    stopInterruptRecognition();
    if (currentAudio) {
      try {
        currentAudio.onended = null;
        currentAudio.onerror = null;
        currentAudio.pause();
        currentAudio.src = "";
      } catch (e) {}
      currentAudio = null;
    }
  }

  function stopInterruptRecognition() {
    if (!interruptRecognition) return;
    try {
      interruptRecognition.onend = null;
      interruptRecognition.onerror = null;
      interruptRecognition.onresult = null;
      interruptRecognition.abort();
    } catch (e) {}
    interruptRecognition = null;
  }

  function looksLikeEcho(transcript, spoken) {
    if (!transcript || !spoken) return false;
    const a = transcript.toLowerCase().replace(/[^\w\s]/g, " ").replace(/\s+/g, " ").trim();
    const b = spoken.toLowerCase().replace(/[^\w\s]/g, " ").replace(/\s+/g, " ").trim();
    if (!a || a.length < 4) return true;
    // If user transcript is mostly contained in what Hope is saying, treat as echo
    if (b.includes(a) && a.length < 40) return true;
    const aw = a.split(" ").filter(Boolean);
    const bw = new Set(b.split(" ").filter(Boolean));
    if (aw.length >= 3) {
      const overlap = aw.filter((w) => bw.has(w)).length / aw.length;
      if (overlap > 0.7) return true;
    }
    return false;
  }

  function startInterruptListening(onInterrupt) {
    stopInterruptRecognition();
    const SpeechRecognition =
      window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) return;

    const recog = new SpeechRecognition();
    interruptRecognition = recog;
    recog.continuous = true;
    recog.interimResults = true;
    recog.lang = "en-US";
    recog.maxAlternatives = 1;

    recog.onresult = (event) => {
      if (!interruptEnabled || !isSpeaking) return;

      let finalText = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          finalText += event.results[i][0].transcript;
        }
      }
      finalText = (finalText || "").trim();
      if (!finalText) return;
      if (looksLikeEcho(finalText, spokenTextForFilter)) {
        console.log("[Interrupt] Ignored likely echo:", finalText);
        return;
      }

      console.log("[Interrupt] User cut in:", finalText);
      interruptEnabled = false;
      stopSpeaking();
      stopRecognition();
      onInterrupt(finalText);
    };

    recog.onerror = (event) => {
      console.log("[Interrupt] Error:", event.error);
      // Keep trying while Hope is still speaking
      if (isSpeaking && interruptEnabled && event.error !== "not-allowed") {
        setTimeout(() => {
          if (isSpeaking && interruptEnabled) startInterruptListening(onInterrupt);
        }, 400);
      }
    };

    recog.onend = () => {
      if (isSpeaking && interruptEnabled) {
        setTimeout(() => {
          if (isSpeaking && interruptEnabled) {
            try {
              recog.start();
            } catch (e) {}
          }
        }, 250);
      }
    };

    try {
      recog.start();
    } catch (e) {
      console.warn("[Interrupt] start failed:", e);
    }
  }

  async function speakText(text, { allowInterrupt = true } = {}) {
    stopSpeaking();

    const speakRes = await fetch(`${window.BACKEND_URL}/speak`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    if (!speakRes.ok) throw new Error("Speak failed");

    const audioBlob = await speakRes.blob();
    const audioUrl = URL.createObjectURL(audioBlob);
    const audio = new Audio(audioUrl);
    currentAudio = audio;
    isSpeaking = true;
    spokenTextForFilter = text || "";

    return await new Promise((resolve, reject) => {
      let settled = false;
      const finish = (payload) => {
        if (settled) return;
        settled = true;
        interruptEnabled = false;
        isSpeaking = false;
        stopInterruptRecognition();
        try {
          URL.revokeObjectURL(audioUrl);
        } catch (e) {}
        if (currentAudio === audio) currentAudio = null;
        resolve(payload);
      };

      audio.onended = () => finish({ interrupted: false });
      audio.onerror = () => finish({ interrupted: false, error: true });

      audio
        .play()
        .then(() => {
          // Small grace period so Hope's first words don't false-trigger
          if (allowInterrupt && isMicOn()) {
            setTimeout(() => {
              if (!isSpeaking || currentAudio !== audio) return;
              interruptEnabled = true;
              setStatus("Speaking… (you can interrupt)", true);
              startInterruptListening((userText) => {
                finish({ interrupted: true, transcript: userText });
              });
            }, 450);
          }
        })
        .catch((err) => {
          finish({ interrupted: false, error: true });
          reject(err);
        });
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

  function resumeAfterHope() {
    if (isMicOn()) {
      setStatus("Get ready…", true);
      setTimeout(() => startCommandMode(), 1200);
    } else {
      startWakeWordMode();
    }
  }

  function safeRestartWake() {
    if (mode !== "wake" || window.hopeIsProcessing) return;
    if (isMicOn()) {
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
    const { micLabel, ta } = getEls();
    if (micLabel) micLabel.classList.add("listening-active");
    restartAttempts = 0;

    stopRecognition();
    recognition = createRecognition();
    if (!recognition) return;

    recognition.continuous = true;
    recognition.interimResults = true;

    recognition.onresult = async (event) => {
      let transcript = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        if (event.results[i].isFinal) {
          transcript += event.results[i][0].transcript;
        }
      }
      transcript = transcript.trim();
      if (!transcript) return;

      console.log("[Command] Heard:", transcript);
      stopRecognition();
      if (ta) {
        ta.value = transcript;
        autoresize();
      }
      await handleVoiceCommand(transcript);
    };

    recognition.onerror = (event) => {
      console.log("[Command] Error:", event.error);
      if (micLabel) micLabel.classList.remove("listening-active");
      if (window.hopeIsProcessing) return;

      if (isMicOn()) {
        const delay =
          event.error === "no-speech" || event.error === "aborted" ? 700 : 900;
        setTimeout(() => startCommandMode(), delay);
      } else {
        setTimeout(() => startWakeWordMode(), 600);
      }
    };

    recognition.onend = () => {
      if (micLabel) micLabel.classList.remove("listening-active");
      if (mode === "command" && !window.hopeIsProcessing) {
        if (isMicOn()) {
          setTimeout(() => startCommandMode(), 600);
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
        setTimeout(() => startCommandMode(), 800);
      } else {
        startWakeWordMode();
      }
    }
  }
  window.startCommandMode = startCommandMode;

  async function handleVoiceCommand(text) {
    if (window.hopeIsProcessing) {
      // If user interrupts, force cut-over to the new utterance
      stopSpeaking();
    }
    window.hopeIsProcessing = true;
    setStatus("Thinking…");

    const { chatThread, micLabel, ta } = getEls();
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
      const result = await speakText(reply, { allowInterrupt: true });

      // User interrupted mid-sentence → handle the new direction
      if (result && result.interrupted && result.transcript) {
        window.hopeIsProcessing = false;
        if (ta) {
          ta.value = result.transcript;
          autoresize();
        }
        setStatus("Interrupted — following you…", true);
        await handleVoiceCommand(result.transcript);
        return;
      }
    } catch (err) {
      console.error("TTS error:", err);
      stopSpeaking();
    }

    window.hopeIsProcessing = false;
    resumeAfterHope();
  }
  window.handleVoiceCommand = handleVoiceCommand;

  function wireMic() {
    const { micCheckbox } = getEls();
    if (!micCheckbox) return;

    micCheckbox.addEventListener("change", () => {
      if (micCheckbox.checked) {
        startCommandMode();
      } else {
        mode = "wake";
        stopSpeaking();
        stopRecognition();
        startWakeWordMode();
      }
    });
  }

  function initVoice() {
    wireMic();
    console.log("[Voice] Ready (continuous + interrupt)");
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initVoice);
  } else {
    initVoice();
  }
})();
