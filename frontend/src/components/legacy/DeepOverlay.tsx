import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { Loader2, Mic, MicOff, Sparkles, X } from "lucide-react";
import {
  MicLevelMeter,
  VoiceController,
  isSpeechRecognitionSupported,
  primeVoices,
  speak,
  type ListenerPhase,
} from "@/lib/speech";
import {
  applyActions,
  askDeep,
  buildSnapshot,
  fetchCapabilities,
  type ActionHandlers,
  type AgentCapabilities,
  type SnapshotInputs,
} from "@/lib/deep-client";
import { DeepAvatar, type AvatarState } from "./DeepAvatar";
import "./DeepOverlay.css";

interface DeepOverlayProps {
  snapshotInputs: SnapshotInputs;
  handlers: ActionHandlers;
}

interface Turn {
  role: "user" | "assistant";
  content: string;
  actions?: string[];
}

const MAX_TURNS = 8;

/**
 * Deep's on-screen presence.
 *
 * Wake word brings the dolphin in from scattered particles; the command is
 * transcribed, sent to the agent with a snapshot of the console, and the
 * returned actions are applied while Deep speaks the reply.
 */
export function DeepOverlay({ snapshotInputs, handlers }: DeepOverlayProps) {
  const [phase, setPhase] = useState<ListenerPhase>("off");
  const [avatar, setAvatar] = useState<AvatarState>("hidden");
  const [visible, setVisible] = useState(false);
  const [partial, setPartial] = useState("");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [capabilities, setCapabilities] = useState<AgentCapabilities | null>(null);
  const [micLevel, setMicLevel] = useState(0);

  const voiceRef = useRef<VoiceController | null>(null);
  const meterRef = useRef<MicLevelMeter | null>(null);
  const inputsRef = useRef(snapshotInputs);
  const handlersRef = useRef(handlers);
  const hideTimer = useRef<number | null>(null);
  const levelFrame = useRef<number>(0);

  // Keep the latest props reachable from callbacks without re-subscribing.
  useEffect(() => {
    inputsRef.current = snapshotInputs;
  }, [snapshotInputs]);
  useEffect(() => {
    handlersRef.current = handlers;
  }, [handlers]);

  const supported = useMemo(() => isSpeechRecognitionSupported(), []);

  /* ---------------------------------------------------------------------- */
  /* Capabilities                                                            */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    const controller = new AbortController();
    fetchCapabilities(controller.signal)
      .then(setCapabilities)
      .catch(() => setCapabilities(null));
    primeVoices();
    return () => controller.abort();
  }, []);

  /* ---------------------------------------------------------------------- */
  /* Presence                                                                */
  /* ---------------------------------------------------------------------- */
  const show = useCallback(() => {
    if (hideTimer.current !== null) {
      window.clearTimeout(hideTimer.current);
      hideTimer.current = null;
    }
    setVisible(true);
    setAvatar((current) => (current === "hidden" ? "assembling" : current));
    // Assembly runs for 1.5s; settle into idle when it completes.
    window.setTimeout(() => {
      setAvatar((current) => (current === "assembling" ? "listening" : current));
    }, 1550);
  }, []);

  const dismiss = useCallback(() => {
    setAvatar("hidden");
    setPartial("");
    voiceRef.current?.returnToWake();
    hideTimer.current = window.setTimeout(() => {
      setVisible(false);
      setTurns([]);
    }, 700);
  }, []);

  /* ---------------------------------------------------------------------- */
  /* Talking to the agent                                                    */
  /* ---------------------------------------------------------------------- */
  const submit = useCallback(
    async (transcript: string) => {
      const text = transcript.trim();
      if (!text) return;

      setPartial("");
      setError(null);
      setBusy(true);
      setAvatar("thinking");
      setTurns((prev) =>
        [...prev, { role: "user" as const, content: text }].slice(-MAX_TURNS),
      );

      // Deep must not hear itself; hold the microphone while it replies.
      voiceRef.current?.suspend();

      try {
        const snapshot = buildSnapshot(inputsRef.current);
        const history = turns.map((t) => ({ role: t.role, content: t.content }));
        const response = await askDeep(text, snapshot, history);

        applyActions(response.actions, {
          ...handlersRef.current,
          dismiss,
        });

        setTurns((prev) =>
          [
            ...prev,
            {
              role: "assistant" as const,
              content: response.reply,
              actions: response.actions.map((a) => a.label).filter(Boolean),
            },
          ].slice(-MAX_TURNS),
        );

        if (response.reply) {
          setAvatar("speaking");
          speak(response.reply, {
            onEnd: () => {
              setAvatar((current) => (current === "speaking" ? "listening" : current));
              voiceRef.current?.resume();
            },
          });
        } else {
          setAvatar("listening");
          voiceRef.current?.resume();
        }

        if (!response.listening) dismiss();
      } catch (caught) {
        const message =
          caught instanceof Error ? caught.message : "Deep could not respond.";
        setError(message);
        setAvatar("listening");
        voiceRef.current?.resume();
      } finally {
        setBusy(false);
      }
    },
    [turns, dismiss],
  );

  /* ---------------------------------------------------------------------- */
  /* Voice wiring                                                            */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    if (!supported) return;

    const controller = new VoiceController({
      onPhase: setPhase,
      onPartial: (text) => setPartial(text),
      onWake: () => {
        show();
        setError(null);
      },
      onFinal: (text) => {
        show();
        void submit(text);
      },
      onError: (message) => setError(message),
    });

    voiceRef.current = controller;
    // Deliberately not started here. Microphone access needs a user gesture,
    // and opening the mic on page load without one is both blocked by some
    // browsers and rude. The first click on the Deep dock begins listening.

    return () => {
      controller.dispose();
      voiceRef.current = null;
    };
  }, [supported, show]);

  // `submit` is rebuilt every turn. Recreating the controller would drop the
  // microphone mid-conversation, so swap the callbacks in place instead.
  const submitRef = useRef(submit);
  useEffect(() => {
    submitRef.current = submit;
  }, [submit]);

  useEffect(() => {
    voiceRef.current?.setEvents({
      onPhase: setPhase,
      onPartial: setPartial,
      onWake: () => {
        show();
        setError(null);
      },
      onFinal: (text) => {
        show();
        void submitRef.current(text);
      },
      onError: setError,
    });
  }, [show]);

  /* ---------------------------------------------------------------------- */
  /* Microphone level, for the speaking animation                            */
  /* ---------------------------------------------------------------------- */
  useEffect(() => {
    if (!visible) return;

    const meter = new MicLevelMeter();
    meterRef.current = meter;
    let cancelled = false;

    void meter.start().then((ok) => {
      if (!ok || cancelled) return;
      const tick = () => {
        levelFrame.current = requestAnimationFrame(tick);
        setMicLevel(meter.level());
      };
      levelFrame.current = requestAnimationFrame(tick);
    });

    return () => {
      cancelled = true;
      cancelAnimationFrame(levelFrame.current);
      meter.stop();
      meterRef.current = null;
      setMicLevel(0);
    };
  }, [visible]);

  /* ---------------------------------------------------------------------- */
  /* Controls                                                                */
  /* ---------------------------------------------------------------------- */
  const toggleListening = useCallback(() => {
    const controller = voiceRef.current;
    if (!controller) return;

    if (phase === "off" || phase === "denied") {
      controller.start();
      show();
      controller.enterCommandMode();
    } else {
      controller.stop();
      dismiss();
    }
  }, [phase, show, dismiss]);

  // Ctrl+Shift+D summons Deep without speaking, for noisy rooms.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.ctrlKey && event.shiftKey && event.code === "KeyD") {
        event.preventDefault();
        toggleListening();
      }
      if (event.code === "Escape" && visible) dismiss();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggleListening, visible, dismiss]);

  const active = phase === "waking" || phase === "command";
  const lastAssistant = [...turns].reverse().find((t) => t.role === "assistant");

  return (
    <>
      {/* ---- Persistent launcher ------------------------------------------ */}
      <button
        className={`deepDock${active ? " deepDock--live" : ""}`}
        onClick={toggleListening}
        type="button"
        title={
          supported
            ? active
              ? "Deep is listening — Ctrl+Shift+D"
              : "Wake Deep — say “Deep”, or Ctrl+Shift+D"
            : "Voice is not supported in this browser"
        }
        disabled={!supported}
      >
        {!supported ? (
          <MicOff size={16} />
        ) : active ? (
          <Mic size={16} />
        ) : (
          <Sparkles size={16} />
        )}
        <span className="deepDock__label">Deep</span>
        {active && <span className="deepDock__pulse" aria-hidden />}
      </button>

      {/* ---- Stage -------------------------------------------------------- */}
      {visible && (
        <div className="deepStage" role="status" aria-live="polite">
          <div className="deepStage__avatar">
            <DeepAvatar state={avatar} size={300} level={micLevel} />
          </div>

          <div className="deepStage__panel">
            <header className="deepStage__head">
              <span className="deepStage__name">DEEP</span>
              <span className={`deepStage__state deepStage__state--${avatar}`}>
                {avatar === "assembling" && "waking"}
                {avatar === "listening" && "listening"}
                {avatar === "thinking" && "thinking"}
                {avatar === "speaking" && "speaking"}
                {avatar === "idle" && "ready"}
              </span>
              <button
                className="deepStage__close"
                onClick={dismiss}
                type="button"
                aria-label="Dismiss Deep"
              >
                <X size={14} />
              </button>
            </header>

            <div className="deepStage__transcript">
              {turns.slice(-4).map((turn, index) => (
                <div key={index} className={`deepTurn deepTurn--${turn.role}`}>
                  <p className="deepTurn__text">{turn.content}</p>
                  {turn.actions && turn.actions.length > 0 && (
                    <ul className="deepTurn__actions">
                      {turn.actions.map((label, i) => (
                        <li key={i}>{label}</li>
                      ))}
                    </ul>
                  )}
                </div>
              ))}

              {partial && (
                <div className="deepTurn deepTurn--user deepTurn--partial">
                  <p className="deepTurn__text">{partial}</p>
                </div>
              )}

              {busy && (
                <div className="deepStage__busy">
                  <Loader2 size={13} className="spin" aria-hidden />
                  <span>Thinking…</span>
                </div>
              )}

              {error && <p className="deepStage__error">{error}</p>}
            </div>

            {turns.length === 0 && !partial && capabilities && (
              <ul className="deepStage__hints">
                {capabilities.examples.slice(0, 4).map((example) => (
                  <li key={example}>
                    <button type="button" onClick={() => void submit(example)}>
                      {example}
                    </button>
                  </li>
                ))}
              </ul>
            )}

            {lastAssistant && capabilities && !capabilities.llm && (
              <p className="deepStage__foot">
                Offline command mode · {capabilities.intents.length} intents
              </p>
            )}
          </div>
        </div>
      )}
    </>
  );
}
