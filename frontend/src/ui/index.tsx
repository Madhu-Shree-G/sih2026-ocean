/**
 * The component kit.
 *
 * Small, unopinionated primitives. Anything with a semantic requirement
 * (labelled controls, expandable explanations, sortable table headers) has
 * the accessibility built in here rather than left to each call site, so a
 * view cannot accidentally ship an unlabelled button.
 */

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { AlertTriangle, ChevronRight, Info, Loader2, X, CheckCircle2 } from "lucide-react";
import "./ui.css";

type Tone = "info" | "warn" | "danger" | "ok" | "neutral";

/* ========================================================================== */
/* Card                                                                       */
/* ========================================================================== */

export function Card({
  children,
  className = "",
  variant,
  as: Tag = "section",
  ...rest
}: {
  children: ReactNode;
  className?: string;
  variant?: "flat" | "sunken" | "accent";
  as?: "section" | "div" | "article" | "aside";
} & React.HTMLAttributes<HTMLElement>) {
  const variantClass = variant ? ` card--${variant}` : "";
  return (
    <Tag className={`card${variantClass} ${className}`} {...rest}>
      {children}
    </Tag>
  );
}

export function CardHead({
  title,
  subtitle,
  actions,
  plain,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
  plain?: boolean;
}) {
  return (
    <header className={`card__head${plain ? " card__head--plain" : ""}`}>
      <div className="card__titles">
        <h3 className="card__title">{title}</h3>
        {subtitle && <p className="card__sub">{subtitle}</p>}
      </div>
      {actions && <div className="row gap2">{actions}</div>}
    </header>
  );
}

export function CardBody({
  children,
  tight,
  className = "",
}: {
  children: ReactNode;
  tight?: boolean;
  className?: string;
}) {
  return <div className={`card__body${tight ? " card__body--tight" : ""} ${className}`}>{children}</div>;
}

export function SectionTitle({
  title,
  subtitle,
  actions,
}: {
  title: ReactNode;
  subtitle?: ReactNode;
  actions?: ReactNode;
}) {
  return (
    <div className="section-title">
      <div>
        <h2>{title}</h2>
        {subtitle && <p>{subtitle}</p>}
      </div>
      {actions}
    </div>
  );
}

/* ========================================================================== */
/* Buttons                                                                    */
/* ========================================================================== */

export function Button({
  children,
  variant = "secondary",
  size,
  block,
  className = "",
  ...rest
}: {
  children: ReactNode;
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "lg";
  block?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`btn btn--${variant}${size ? ` btn--${size}` : ""}${block ? " btn--block" : ""} ${className}`}
      {...rest}
    >
      {children}
    </button>
  );
}

/** Icon-only button. `label` is mandatory — it becomes both tooltip and name. */
export function IconButton({
  icon,
  label,
  active,
  bordered,
  large,
  className = "",
  ...rest
}: {
  icon: ReactNode;
  label: string;
  active?: boolean;
  bordered?: boolean;
  large?: boolean;
} & React.ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      className={`iconbtn${active ? " iconbtn--on" : ""}${bordered ? " iconbtn--bordered" : ""}${
        large ? " iconbtn--lg" : ""
      } ${className}`}
      aria-label={label}
      aria-pressed={active}
      title={label}
      {...rest}
    >
      {icon}
    </button>
  );
}

/* ========================================================================== */
/* Segmented control                                                          */
/* ========================================================================== */

export interface SegmentOption<T extends string> {
  value: T;
  label: ReactNode;
  icon?: ReactNode;
  title?: string;
}

export function Segmented<T extends string>({
  value,
  options,
  onChange,
  large,
  label,
}: {
  value: T;
  options: SegmentOption<T>[];
  onChange: (value: T) => void;
  large?: boolean;
  label: string;
}) {
  return (
    <div className={`segmented${large ? " segmented--lg" : ""}`} role="group" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          className="segmented__item"
          aria-pressed={value === option.value}
          title={option.title}
          onClick={() => onChange(option.value)}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}

/* ========================================================================== */
/* Badge, dot, meter                                                          */
/* ========================================================================== */

export function Badge({
  children,
  tone = "neutral",
  icon,
}: {
  children: ReactNode;
  tone?: Tone;
  icon?: ReactNode;
}) {
  return (
    <span className={`badge badge--${tone}`}>
      {icon}
      {children}
    </span>
  );
}

export function Dot({ color }: { color: string }) {
  return <span className="dot" style={{ background: color }} aria-hidden />;
}

export function Meter({
  value,
  min,
  max,
  color,
  minLabel,
  maxLabel,
  label,
}: {
  value: number;
  min: number;
  max: number;
  color?: string;
  minLabel?: string;
  maxLabel?: string;
  label: string;
}) {
  const span = max - min;
  const fraction = span > 0 ? (value - min) / span : 0;
  const percent = Math.max(0, Math.min(100, fraction * 100));
  return (
    <div
      className="meter"
      role="meter"
      aria-valuenow={Number(value.toFixed(2))}
      aria-valuemin={min}
      aria-valuemax={max}
      aria-label={label}
    >
      <div className="meter__track">
        <div
          className="meter__fill"
          style={{ width: `${percent}%`, ...(color ? { ["--meter-color" as string]: color } : {}) }}
        />
      </div>
      {(minLabel || maxLabel) && (
        <div className="meter__scale">
          <span>{minLabel}</span>
          <span>{maxLabel}</span>
        </div>
      )}
    </div>
  );
}

/* ========================================================================== */
/* Stat                                                                       */
/* ========================================================================== */

export function Stat({
  label,
  value,
  note,
  tone,
  small,
}: {
  label: ReactNode;
  value: ReactNode;
  note?: ReactNode;
  tone?: "danger" | "warn" | "ok";
  small?: boolean;
}) {
  return (
    <div className={`stat${tone ? ` stat--${tone}` : ""}`}>
      <span className="stat__label">{label}</span>
      <span className={`stat__value${small ? " stat__value--sm" : ""}`}>{value}</span>
      {note && <span className="stat__note">{note}</span>}
    </div>
  );
}

export function StatGrid({ children }: { children: ReactNode }) {
  return <div className="statgrid">{children}</div>;
}

/* ========================================================================== */
/* Form controls                                                              */
/* ========================================================================== */

export function Field({
  label,
  hint,
  children,
  htmlFor,
}: {
  label: ReactNode;
  hint?: ReactNode;
  children: ReactNode;
  htmlFor?: string;
}) {
  return (
    <div className="field">
      <label className="field__label" htmlFor={htmlFor}>
        {label}
      </label>
      {children}
      {hint && <span className="field__hint">{hint}</span>}
    </div>
  );
}

export function Select<T extends string>({
  value,
  options,
  onChange,
  label,
  hint,
  id,
}: {
  value: T;
  options: { value: T; label: string }[];
  onChange: (value: T) => void;
  label: ReactNode;
  hint?: ReactNode;
  id?: string;
}) {
  const generated = useId();
  const selectId = id ?? generated;
  return (
    <Field label={label} hint={hint} htmlFor={selectId}>
      <select
        id={selectId}
        className="control"
        value={value}
        onChange={(event) => onChange(event.target.value as T)}
      >
        {options.map((option) => (
          <option key={option.value} value={option.value}>
            {option.label}
          </option>
        ))}
      </select>
    </Field>
  );
}

export function Switch({
  checked,
  onChange,
  label,
  id,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  id?: string;
}) {
  const generated = useId();
  return (
    <label className="switch" htmlFor={id ?? generated}>
      <input
        id={id ?? generated}
        type="checkbox"
        checked={checked}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="switch__track" aria-hidden />
      <span className="switch__label">{label}</span>
    </label>
  );
}

export function Checkbox({
  checked,
  onChange,
  label,
  disabled,
  accent,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: ReactNode;
  disabled?: boolean;
  accent?: string;
}) {
  const id = useId();
  return (
    <label
      className="check"
      htmlFor={id}
      style={accent ? ({ ["--check-accent" as string]: accent } as React.CSSProperties) : undefined}
    >
      <input
        id={id}
        type="checkbox"
        checked={checked}
        disabled={disabled}
        onChange={(event) => onChange(event.target.checked)}
      />
      <span className="check__box" aria-hidden />
      <span className="switch__label">{label}</span>
    </label>
  );
}

/* ========================================================================== */
/* Callout                                                                    */
/* ========================================================================== */

const TONE_ICON: Record<Tone, typeof Info> = {
  info: Info,
  warn: AlertTriangle,
  danger: AlertTriangle,
  ok: CheckCircle2,
  neutral: Info,
};

export function Callout({
  tone = "info",
  title,
  children,
  icon,
}: {
  tone?: Tone;
  title?: ReactNode;
  children: ReactNode;
  icon?: ReactNode;
}) {
  const Icon = TONE_ICON[tone];
  return (
    <div className={`callout callout--${tone}`}>
      <span className="callout__icon">{icon ?? <Icon size={18} aria-hidden />}</span>
      <div>
        {title && <div className="callout__title">{title}</div>}
        <div>{children}</div>
      </div>
    </div>
  );
}

/* ========================================================================== */
/* Disclosure                                                                 */
/* ========================================================================== */

/**
 * An expandable explanation. Present on every public-facing number, because
 * "27.4 °C" tells a fisher nothing that "about 1 °C warmer than usual for
 * March, which pushes surface fish deeper" tells them.
 */
export function Disclosure({
  summary,
  children,
  defaultOpen = false,
}: {
  summary: ReactNode;
  children: ReactNode;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);
  const id = useId();
  return (
    <div className="disclosure">
      <button
        type="button"
        className="disclosure__btn"
        aria-expanded={open}
        aria-controls={id}
        onClick={() => setOpen((value) => !value)}
      >
        <ChevronRight size={16} className="disclosure__chev" aria-hidden />
        {summary}
      </button>
      {open && (
        <div className="disclosure__body" id={id}>
          {children}
        </div>
      )}
    </div>
  );
}

/* ========================================================================== */
/* Table                                                                      */
/* ========================================================================== */

export function TableWrap({
  children,
  maxHeight,
}: {
  children: ReactNode;
  maxHeight?: number;
}) {
  return (
    <div className="tablewrap scroll" style={maxHeight ? { maxHeight } : undefined}>
      {children}
    </div>
  );
}

/** A sortable column header that announces its state to screen readers. */
export function SortHeader<K extends string>({
  columnKey,
  active,
  direction,
  onSort,
  children,
  numeric,
}: {
  columnKey: K;
  active: boolean;
  direction: "asc" | "desc";
  onSort: (key: K) => void;
  children: ReactNode;
  numeric?: boolean;
}) {
  return (
    <th
      className={numeric ? "num" : undefined}
      aria-sort={active ? (direction === "asc" ? "ascending" : "descending") : "none"}
      scope="col"
    >
      <button type="button" className="tablesort" onClick={() => onSort(columnKey)}>
        {children}
        <span aria-hidden>{active ? (direction === "asc" ? "▲" : "▼") : "↕"}</span>
      </button>
    </th>
  );
}

/** Sorting state shared by every table in the app. */
export function useSort<K extends string>(initial: K, initialDirection: "asc" | "desc" = "asc") {
  const [key, setKey] = useState<K>(initial);
  const [direction, setDirection] = useState<"asc" | "desc">(initialDirection);

  const onSort = useCallback(
    (next: K) => {
      if (next === key) {
        setDirection((d) => (d === "asc" ? "desc" : "asc"));
      } else {
        setKey(next);
        setDirection("asc");
      }
    },
    [key],
  );

  const compare = useCallback(
    (a: unknown, b: unknown) => {
      const sign = direction === "asc" ? 1 : -1;
      if (a === null || a === undefined) return 1;
      if (b === null || b === undefined) return -1;
      if (typeof a === "number" && typeof b === "number") return (a - b) * sign;
      return String(a).localeCompare(String(b)) * sign;
    },
    [direction],
  );

  return { key, direction, onSort, compare };
}

/* ========================================================================== */
/* States                                                                     */
/* ========================================================================== */

export function EmptyState({
  icon,
  title,
  body,
  action,
  tone,
}: {
  icon: ReactNode;
  title: ReactNode;
  body?: ReactNode;
  action?: ReactNode;
  tone?: "danger" | "warn";
}) {
  return (
    <div className={`state${tone ? ` state--${tone}` : ""}`}>
      <span className="state__icon">{icon}</span>
      <p className="state__title">{title}</p>
      {body && <div className="state__body">{body}</div>}
      {action}
    </div>
  );
}

export function Loading({ label }: { label: string }) {
  return (
    <div className="state" role="status">
      <Loader2 size={26} className="spin" aria-hidden />
      <p className="state__body">{label}</p>
    </div>
  );
}

export function Skeleton({ height = 16, width = "100%" }: { height?: number; width?: number | string }) {
  return <div className="skeleton" style={{ height, width }} aria-hidden />;
}

/* ========================================================================== */
/* Modal                                                                      */
/* ========================================================================== */

export function Modal({
  title,
  onClose,
  children,
  closeLabel = "Close",
}: {
  title: ReactNode;
  onClose: () => void;
  children: ReactNode;
  closeLabel?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  // Escape closes, and focus moves into the dialog so the keyboard is not
  // stranded behind the scrim.
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (event.key === "Escape") onClose();
    };
    document.addEventListener("keydown", onKey);
    ref.current?.focus();
    return () => document.removeEventListener("keydown", onKey);
  }, [onClose]);

  return (
    <div className="scrim" onPointerDown={(event) => event.target === event.currentTarget && onClose()}>
      <div className="modal" role="dialog" aria-modal="true" aria-label={typeof title === "string" ? title : undefined} tabIndex={-1} ref={ref}>
        <header className="modal__head">
          <h2 className="modal__title">{title}</h2>
          <IconButton icon={<X size={18} />} label={closeLabel} onClick={onClose} />
        </header>
        <div className="modal__body scroll">{children}</div>
      </div>
    </div>
  );
}

/* ========================================================================== */
/* Tabs                                                                       */
/* ========================================================================== */

export function Tabs<T extends string>({
  value,
  options,
  onChange,
  label,
}: {
  value: T;
  options: { value: T; label: ReactNode; icon?: ReactNode }[];
  onChange: (value: T) => void;
  label: string;
}) {
  return (
    <div className="tabs" role="tablist" aria-label={label}>
      {options.map((option) => (
        <button
          key={option.value}
          type="button"
          role="tab"
          className="tab"
          aria-selected={value === option.value}
          onClick={() => onChange(option.value)}
        >
          {option.icon}
          {option.label}
        </button>
      ))}
    </div>
  );
}

/* ========================================================================== */
/* Toasts                                                                     */
/* ========================================================================== */

interface Toast {
  id: number;
  message: string;
}

const ToastContext = createContext<(message: string) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const counter = useRef(0);

  const push = useCallback((message: string) => {
    const id = ++counter.current;
    setToasts((current) => [...current, { id, message }]);
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id));
    }, 3200);
  }, []);

  const value = useMemo(() => push, [push]);

  return (
    <ToastContext.Provider value={value}>
      {children}
      {/* Polite, not assertive: a confirmation must not interrupt a screen
          reader mid-sentence. */}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((toast) => (
          <div className="toast" key={toast.id}>
            <CheckCircle2 size={16} aria-hidden />
            {toast.message}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export function useToast() {
  return useContext(ToastContext);
}
