/**
 * Voice input and output for Deep, over the Web Speech API.
 *
 * Two things make this harder than the API suggests:
 *
 * 1. Continuous recognition stops on its own — on silence, on error, and on
 *    some browsers after roughly a minute. A wake-word listener therefore has
 *    to restart itself, but restarting too eagerly after a permission denial
 *    produces an infinite loop. The controller below tracks *why* it stopped.
 *
 * 2. The microphone cannot be shared. While Deep speaks, recognition must be
 *    suspended or it transcribes its own voice and answers itself.
 */

/* eslint-disable @typescript-eslint/no-explicit-any */

export interface SpeechRecognitionLike {
  lang: string;
  continuous: boolean;
  interimResults: boolean;
  maxAlternatives: number;
  start(): void;
  stop(): void;
  abort(): void;
  onresult: ((event: any) => void) | null;
  onerror: ((event: any) => void) | null;
  onend: (() => void) | null;
  onstart: (() => void) | null;
}

function recognitionConstructor(): (new () => SpeechRecognitionLike) | null {
  const w = window as any;
  return w.SpeechRecognition ?? w.webkitSpeechRecognition ?? null;
}

export function isSpeechRecognitionSupported(): boolean {
  return recognitionConstructor() !== null;
}

export function isSpeechSynthesisSupported(): boolean {
  return typeof window !== "undefined" && "speechSynthesis" in window;
}

export type ListenerPhase = "off" | "waking" | "command" | "denied" | "unsupported";

export interface VoiceEvents {
  /** Final transcript of a complete utterance. */
  onFinal?: (transcript: string) => void;
  /** Live partial transcript, for on-screen feedback. */
  onPartial?: (transcript: string) => void;
  /** The wake word was heard while idle. */
  onWake?: (remainder: string) => void;
  onPhase?: (phase: ListenerPhase) => void;
  onError?: (message: string) => void;
}

const WAKE_PATTERN = /\b(hey\s+|ok(?:ay)?\s+)?(deep|dee+p|dip)\b/i;

/** Strip a leading address to the agent from a transcript. */
export function splitWakeWord(transcript: string): { woke: boolean; rest: string } {
  const match = WAKE_PATTERN.exec(transcript);
  if (!match) return { woke: false, rest: transcript.trim() };
  return {
    woke: true,
    rest: transcript.slice(match.index + match[0].length).replace(/^[\s,.]+/, "").trim(),
  };
}

export class VoiceController {
  private recognition: SpeechRecognitionLike | null = null;
  private phase: ListenerPhase = "off";
  private events: VoiceEvents;
  private wantRunning = false;
  private suspended = false;
  private restartTimer: number | null = null;
  private lang: string;

  constructor(events: VoiceEvents, lang = "en-IN") {
    this.events = events;
    this.lang = lang;
  }

  get currentPhase(): ListenerPhase {
    return this.phase;
  }

  /**
   * Swap the callbacks without tearing down recognition.
   *
   * The React layer rebuilds its handlers on every conversational turn, but
   * recreating the controller would drop the microphone mid-conversation.
   */
  setEvents(events: VoiceEvents): void {
    this.events = events;
  }

  private setPhase(phase: ListenerPhase): void {
    if (this.phase === phase) return;
    this.phase = phase;
    this.events.onPhase?.(phase);
  }

  private build(): SpeechRecognitionLike | null {
    const Ctor = recognitionConstructor();
    if (!Ctor) {
      this.setPhase("unsupported");
      return null;
    }

    const recognition = new Ctor();
    recognition.lang = this.lang;
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.maxAlternatives = 1;

    recognition.onresult = (event: any) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        const text: string = result[0]?.transcript ?? "";
        if (result.isFinal) {
          this.handleFinal(text.trim());
        } else {
          interim += text;
        }
      }
      if (interim.trim()) this.events.onPartial?.(interim.trim());
    };

    recognition.onerror = (event: any) => {
      const code = event?.error ?? "unknown";

      if (code === "not-allowed" || code === "service-not-allowed") {
        // Permission was refused. Restarting would loop forever.
        this.wantRunning = false;
        this.setPhase("denied");
        this.events.onError?.(
          "Microphone access was blocked. Enable it in the browser to use Deep.",
        );
        return;
      }

      // "no-speech" and "aborted" are routine in continuous mode; the onend
      // handler restarts, so they are not surfaced to the user.
      if (code !== "no-speech" && code !== "aborted") {
        this.events.onError?.(`Speech recognition error: ${code}`);
      }
    };

    recognition.onend = () => {
      // Continuous recognition ends on its own; restart if we still want it.
      if (this.wantRunning && !this.suspended) this.scheduleRestart();
      else if (!this.wantRunning) this.setPhase("off");
    };

    return recognition;
  }

  private handleFinal(text: string): void {
    if (!text) return;

    if (this.phase === "command") {
      this.events.onFinal?.(text);
      return;
    }

    const { woke, rest } = splitWakeWord(text);
    if (woke) {
      this.setPhase("command");
      this.events.onWake?.(rest);
      // A command spoken in the same breath as the wake word is honoured
      // immediately: "Deep, show salinity".
      if (rest) this.events.onFinal?.(rest);
    }
  }

  private scheduleRestart(delay = 260): void {
    if (this.restartTimer !== null) return;
    this.restartTimer = window.setTimeout(() => {
      this.restartTimer = null;
      if (!this.wantRunning || this.suspended) return;
      try {
        this.recognition?.start();
      } catch {
        // start() throws if it is already running; harmless.
      }
    }, delay);
  }

  /** Begin listening for the wake word. */
  start(): void {
    if (this.phase === "denied" || this.phase === "unsupported") return;

    if (!this.recognition) {
      this.recognition = this.build();
      if (!this.recognition) return;
    }

    this.wantRunning = true;
    this.suspended = false;
    this.setPhase("waking");
    try {
      this.recognition.start();
    } catch {
      // Already started.
    }
  }

  stop(): void {
    this.wantRunning = false;
    this.suspended = false;
    if (this.restartTimer !== null) {
      window.clearTimeout(this.restartTimer);
      this.restartTimer = null;
    }
    try {
      this.recognition?.stop();
    } catch {
      /* not running */
    }
    this.setPhase("off");
  }

  /** Drop back to wake-word mode after a command has been handled. */
  returnToWake(): void {
    if (this.wantRunning) this.setPhase("waking");
  }

  /** Enter command mode without a spoken wake word (button press). */
  enterCommandMode(): void {
    if (!this.wantRunning) this.start();
    this.setPhase("command");
  }

  /**
   * Pause the microphone while Deep speaks, so it does not transcribe itself.
   */
  suspend(): void {
    if (!this.wantRunning) return;
    this.suspended = true;
    try {
      this.recognition?.abort();
    } catch {
      /* not running */
    }
  }

  resume(): void {
    if (!this.wantRunning) return;
    this.suspended = false;
    this.scheduleRestart(160);
  }

  dispose(): void {
    this.stop();
    if (this.recognition) {
      this.recognition.onresult = null;
      this.recognition.onerror = null;
      this.recognition.onend = null;
      this.recognition = null;
    }
  }
}

/* ========================================================================== */
/* Speech synthesis                                                           */
/* ========================================================================== */

let cachedVoice: SpeechSynthesisVoice | null = null;

/**
 * Pick a voice. Indian English first, since this is an INCOIS console and the
 * domain vocabulary is read more naturally by it; then any English voice.
 */
function pickVoice(): SpeechSynthesisVoice | null {
  if (cachedVoice) return cachedVoice;
  if (!isSpeechSynthesisSupported()) return null;

  const voices = window.speechSynthesis.getVoices();
  if (voices.length === 0) return null;

  cachedVoice =
    voices.find((v) => v.lang === "en-IN") ??
    voices.find((v) => v.lang?.startsWith("en-GB")) ??
    voices.find((v) => v.lang?.startsWith("en")) ??
    voices[0];

  return cachedVoice;
}

export interface SpeakHandle {
  cancel(): void;
}

/** Speak a line, resolving when playback finishes. */
export function speak(
  text: string,
  options: { onStart?: () => void; onEnd?: () => void; rate?: number } = {},
): SpeakHandle {
  if (!isSpeechSynthesisSupported() || !text.trim()) {
    options.onEnd?.();
    return { cancel: () => undefined };
  }

  const synth = window.speechSynthesis;
  synth.cancel();

  const utterance = new SpeechSynthesisUtterance(text);
  const voice = pickVoice();
  if (voice) {
    utterance.voice = voice;
    utterance.lang = voice.lang;
  }
  // Slightly quick and slightly low: it reads as competent rather than perky.
  utterance.rate = options.rate ?? 1.06;
  utterance.pitch = 0.95;
  utterance.volume = 1;

  utterance.onstart = () => options.onStart?.();
  utterance.onend = () => options.onEnd?.();
  utterance.onerror = () => options.onEnd?.();

  synth.speak(utterance);
  return { cancel: () => synth.cancel() };
}

/** Voice lists load asynchronously in some browsers; warm the cache early. */
export function primeVoices(): void {
  if (!isSpeechSynthesisSupported()) return;
  const synth = window.speechSynthesis;
  if (synth.getVoices().length === 0) {
    synth.addEventListener("voiceschanged", () => pickVoice(), { once: true });
  } else {
    pickVoice();
  }
}

/* ========================================================================== */
/* Microphone level                                                           */
/* ========================================================================== */

/**
 * Track microphone loudness so the avatar can react to the voice.
 * Entirely optional: if permission is refused the level stays at zero.
 */
export class MicLevelMeter {
  private context: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private stream: MediaStream | null = null;
  private data: Uint8Array | null = null;

  async start(): Promise<boolean> {
    if (this.analyser) return true;
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: true });
      const Ctor = window.AudioContext ?? (window as any).webkitAudioContext;
      this.context = new Ctor();
      const source = this.context.createMediaStreamSource(this.stream);
      this.analyser = this.context.createAnalyser();
      this.analyser.fftSize = 256;
      source.connect(this.analyser);
      this.data = new Uint8Array(this.analyser.frequencyBinCount);
      return true;
    } catch {
      this.stop();
      return false;
    }
  }

  /** Current loudness, 0..1. */
  level(): number {
    if (!this.analyser || !this.data) return 0;
    this.analyser.getByteFrequencyData(this.data as any);
    let sum = 0;
    for (let i = 0; i < this.data.length; i++) sum += this.data[i];
    return Math.min(1, sum / this.data.length / 96);
  }

  stop(): void {
    this.stream?.getTracks().forEach((track) => track.stop());
    this.context?.close().catch(() => undefined);
    this.stream = null;
    this.context = null;
    this.analyser = null;
    this.data = null;
  }
}
