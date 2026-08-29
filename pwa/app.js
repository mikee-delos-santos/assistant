// Voice PWA shell. Records audio on hold, will POST it to the brain for
// accent-robust transcription (AS-19), shows the transcript for correction
// (AS-20), then sends the confirmed text to OpenClaw (AS-22) and speaks the
// reply with on-device TTS (AS-21).
//
// Endpoints are placeholders until the brain is up. Nothing here holds secrets.

const els = {
  talk: document.getElementById("talk"),
  send: document.getElementById("send"),
  draft: document.getElementById("draft"),
  transcript: document.getElementById("transcript"),
  status: document.getElementById("status"),
};

// Reached over Tailscale; wired once the brain is running.
const API = {
  transcribe: "/api/transcribe", // audio -> text (server-side STT)
  ask: "/api/ask",               // text -> assistant reply
};

let recorder = null;
let chunks = [];

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("sw.js").catch(() => {});
}

async function startRecording() {
  const stream = await navigator.mediaDevices.getUserMedia({ audio: true });
  recorder = new MediaRecorder(stream);
  chunks = [];
  recorder.ondataavailable = (e) => e.data.size && chunks.push(e.data);
  recorder.start();
  setStatus("Listening...");
}

async function stopRecording() {
  if (!recorder) return;
  const done = new Promise((res) => (recorder.onstop = res));
  recorder.stop();
  recorder.stream.getTracks().forEach((t) => t.stop());
  await done;
  setStatus("Transcribing...");
  const blob = new Blob(chunks, { type: recorder.mimeType || "audio/webm" });
  const text = await transcribe(blob);
  els.draft.hidden = false;
  els.send.hidden = false;
  els.draft.value = text;
  els.draft.focus();
  setStatus("Check the words, fix if needed, then Send.");
}

async function transcribe(blob) {
  try {
    const form = new FormData();
    form.append("audio", blob);
    const r = await fetch(API.transcribe, { method: "POST", body: form });
    if (!r.ok) throw new Error(r.statusText);
    return (await r.json()).text ?? "";
  } catch {
    return "[transcription endpoint not wired yet]";
  }
}

async function ask(text) {
  setStatus("Thinking...");
  try {
    const r = await fetch(API.ask, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const reply = (await r.json()).reply ?? "";
    appendTurn(text, reply);
    speak(reply);
  } catch {
    appendTurn(text, "[assistant endpoint not wired yet]");
  } finally {
    setStatus("");
  }
}

function speak(text) {
  if (!("speechSynthesis" in window) || !text) return;
  speechSynthesis.speak(new SpeechSynthesisUtterance(text));
}

function appendTurn(you, reply) {
  const t = document.createElement("div");
  t.className = "turn";
  t.innerHTML = `<p class="you"></p><p class="bot"></p>`;
  t.querySelector(".you").textContent = you;
  t.querySelector(".bot").textContent = reply;
  els.transcript.append(t);
  t.scrollIntoView({ behavior: "smooth" });
}

function setStatus(s) {
  els.status.textContent = s;
}

// Hold-to-talk (pointer events cover touch and mouse).
els.talk.addEventListener("pointerdown", (e) => {
  e.preventDefault();
  startRecording().catch(() => setStatus("Mic permission needed."));
});
els.talk.addEventListener("pointerup", () => stopRecording());
els.talk.addEventListener("pointerleave", () => recorder && stopRecording());

els.send.addEventListener("click", () => {
  const text = els.draft.value.trim();
  if (!text) return;
  els.draft.hidden = true;
  els.send.hidden = true;
  ask(text);
});
