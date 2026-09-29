/**
 * Deep — the ocean assistant.
 *
 * The previous version was voice-only. That is the wrong default for this
 * audience: speech recognition on Indian-accented English is unreliable, a
 * boat and a control room are both noisy, and a shared desktop in a district
 * office may have no microphone at all. So typing is the primary path here and
 * voice is an optional extra, offered only when the browser actually supports
 * it. Suggestions come from the backend's own grammar, so what is offered is
 * always something Deep can really do.
 */

import { useCallback, useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Mic, MicOff, Send, Sparkles, X } from "lucide-react";
import { useAppStore } from "@/state/store";
import {
  applyActions,
  askDeep,
  buildSnapshot,
  fetchCapabilities,
  type ActionHandlers,
  type SnapshotInputs,
} from "@/lib/deep-client";
import { isSpeechRecognitionSupported, splitWakeWord, VoiceController } from "@/lib/speech";
import { Button, IconButton } from "@/ui";

interface Message {
  role: "user" | "deep" | "error";
  text: string;
}

interface AssistantProps {
  snapshotInputs: SnapshotInputs;
  handlers: ActionHandlers;
}

export function Assistant({ snapshotInputs, handlers }: AssistantProps) {
  const open = useAppStore((state) => state.assistantOpen);
  const setOpen = useAppStore((state) => state.setAssistantOpen);
  const language = useAppStore((state) => state.language);

  const [messages, setMessages] = useState<Message[]>([]);
  const [draft, setDraft] = useState("");
  const [busy, setBusy] = useState(false);
  const [listening, setListening] = useState(false);
  const [suggestions, setSuggestions] = useState<string[]>([]);

  const logRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLInputElement>(null);
  const voiceRef = useRef<VoiceController | null>(null);

  const capabilities = useQuery({
    queryKey: ["deep-capabilities"],
    queryFn: ({ signal }) => fetchCapabilities(signal),
    enabled: open,
    staleTime: Infinity,
    retry: false,
  });

  useEffect(() => {
    if (capabilities.data?.examples?.length && suggestions.length === 0) {
      setSuggestions(capabilities.data.examples.slice(0, 4));
    }
  }, [capabilities.data, suggestions.length]);

  /* Keep the newest turn in view, and put the caret in the box on open. */
  useEffect(() => {
    logRef.current?.scrollTo({ top: logRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  useEffect(() => {
    if (open) inputRef.current?.focus();
  }, [open]);

  const send = useCallback(
    async (text: string) => {
      const transcript = text.trim();
      if (!transcript || busy) return;

      setMessages((current) => [...current, { role: "user", text: transcript }]);
      setDraft("");
      setBusy(true);

      try {
        const history = messages.slice(-6).map((message) => ({
          role: message.role === "user" ? ("user" as const) : ("assistant" as const),
          content: message.text,
        }));

        const response = await askDeep(transcript, buildSnapshot(snapshotInputs), history);
        applyActions(response.actions, handlers);

        setMessages((current) => [...current, { role: "deep", text: response.reply }]);
        if (response.suggestions?.length) setSuggestions(response.suggestions.slice(0, 4));
      } catch (error) {
        setMessages((current) => [
          ...current,
          { role: "error", text: error instanceof Error ? error.message : "Deep is unavailable." },
        ]);
      } finally {
        setBusy(false);
      }
    },
    [busy, messages, snapshotInputs, handlers],
  );

  /* ---- Voice, when the browser has it ---------------------------------- */
  const voiceSupported = isSpeechRecognitionSupported();

  const toggleVoice = useCallback(() => {
    if (!voiceSupported) return;

    if (listening) {
      voiceRef.current?.stop();
      voiceRef.current = null;
      setListening(false);
      return;
    }

    const controller = new VoiceController(
      {
        onFinal: (transcript) => {
          // "Deep, show salinity" and "show salinity" should behave the same:
          // the button already means the user is addressing the assistant.
          const { rest } = splitWakeWord(transcript);
          void send(rest || transcript);
        },
        onPhase: (phase) => setListening(phase === "command" || phase === "waking"),
        onError: (message) =>
          setMessages((current) => [...current, { role: "error", text: message }]),
      },
      language === "hi" ? "hi-IN" : "en-IN",
    );
    voiceRef.current = controller;
    controller.start();
    setListening(true);
  }, [listening, send, voiceSupported, language]);

  useEffect(() => {
    return () => {
      voiceRef.current?.stop();
      voiceRef.current = null;
    };
  }, []);

  if (!open) return null;

  return (
    <aside className="assistant" aria-label="Deep, the ocean assistant">
      <header className="assistant__head">
        <Sparkles size={18} aria-hidden style={{ color: "var(--accent-text)" }} />
        <div className="grow">
          <p className="assistant__title">Deep</p>
          <p className="assistant__sub">
            {capabilities.data
              ? `Understands ${capabilities.data.intents.length} kinds of request`
              : "Ask about what is on screen"}
          </p>
        </div>
        {voiceSupported && (
          <IconButton
            icon={listening ? <Mic size={17} /> : <MicOff size={17} />}
            label={listening ? "Stop listening" : "Listen for a spoken question"}
            active={listening}
            onClick={toggleVoice}
          />
        )}
        <IconButton icon={<X size={17} />} label="Close the assistant" onClick={() => setOpen(false)} />
      </header>

      <div className="assistant__log" ref={logRef} role="log" aria-live="polite">
        {messages.length === 0 && (
          <p className="bubble bubble--deep">
            Ask me what you are looking at, or tell me where to go — "how warm is the Bay of
            Bengal?", "show salinity", "go to five hundred metres", "where is the heatwave?".
          </p>
        )}
        {messages.map((message, index) => (
          <p key={index} className={`bubble bubble--${message.role}`}>
            {message.text}
          </p>
        ))}
        {busy && <p className="bubble bubble--deep muted">Thinking…</p>}
      </div>

      {suggestions.length > 0 && (
        <div className="assistant__suggestions">
          {suggestions.map((suggestion) => (
            <button
              key={suggestion}
              type="button"
              className="suggestion"
              onClick={() => void send(suggestion)}
              disabled={busy}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}

      <form
        className="assistant__form"
        onSubmit={(event) => {
          event.preventDefault();
          void send(draft);
        }}
      >
        <input
          ref={inputRef}
          className="control"
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Ask about the ocean…"
          aria-label="Ask Deep a question"
          disabled={busy}
        />
        <Button type="submit" variant="primary" disabled={busy || !draft.trim()}>
          <Send size={16} aria-hidden />
          <span className="sr-only">Send</span>
        </Button>
      </form>
    </aside>
  );
}
