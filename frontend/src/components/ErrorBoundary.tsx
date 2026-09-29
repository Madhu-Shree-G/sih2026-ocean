/**
 * Last line of defence.
 *
 * WebGL context loss, a malformed payload or a renderer bug should not leave
 * someone staring at a blank white page with no idea what happened or what to
 * do. This shows what broke and offers the one action that usually fixes it.
 */

import { Component, type ErrorInfo, type ReactNode } from "react";
import { RefreshCw, ServerCrash } from "lucide-react";

interface Props {
  children: ReactNode;
}

interface State {
  error: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo): void {
    // Keep the component stack in the console: it is the only place a
    // developer can get it once the tree has unmounted.
    console.error("Unhandled error in the INDO-FOS interface", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;

    return (
      <div className="view">
        <div className="view__inner">
          <div className="state state--danger" role="alert">
            <span className="state__icon">
              <ServerCrash size={26} />
            </span>
            <p className="state__title">Something in the interface stopped working</p>
            <div className="state__body">
              <p>
                The data services are probably fine — this is a fault in the page itself. Reloading
                usually clears it.
              </p>
              <code>{error.message}</code>
            </div>
            <button className="btn btn--primary" type="button" onClick={() => window.location.reload()}>
              <RefreshCw size={16} aria-hidden />
              Reload the page
            </button>
          </div>
        </div>
      </div>
    );
  }
}
