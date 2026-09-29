/**
 * Translation lookup.
 *
 * No provider and no context: the language already lives in the store, and
 * every component that renders text is already subscribed to it. A second
 * mechanism would only create a way for the two to disagree.
 */

import { useAppStore } from "@/state/store";
import { STRINGS, type Language, type StringKey } from "./strings";

export { LANGUAGE_NAMES } from "./strings";
export type { Language, StringKey } from "./strings";

export type Translate = (key: StringKey) => string;

/** Look a key up outside React (formatters, derived text). */
export function translate(language: Language, key: StringKey): string {
  return STRINGS[language]?.[key] ?? STRINGS.en[key] ?? key;
}

/** `const t = useT()` then `t("nav.today")`. */
export function useT(): Translate {
  const language = useAppStore((state) => state.language);
  return (key: StringKey) => translate(language, key);
}

/** Pick the right half of an already-bilingual pair. */
export function pick(language: Language, en: string, hi: string): string {
  return language === "hi" ? hi : en;
}
