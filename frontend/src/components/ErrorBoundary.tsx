import { Component, type ErrorInfo, type ReactNode } from "react";
import { AlertTriangle } from "lucide-react";
import { Button } from "@/components/ui/button";

interface Props {
  children: ReactNode;
}
interface State {
  error: Error | null;
}

/**
 * App-level error boundary. A render exception anywhere in the control panel
 * (a malformed snapshot field, a chart edge case) would otherwise white-screen
 * the whole UI — and this UI is the operator's kill switch over live positions.
 * The fallback keeps a themed surface, names the error, reassures that the
 * trading engine is a separate process (unaffected), and offers a reload.
 */
export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    // Surface for devtools; the trading loop runs out-of-process and is unaffected.
    console.error("Titan GUI crashed:", error, info.componentStack);
  }

  render() {
    const { error } = this.state;
    if (!error) return this.props.children;
    return (
      <div role="alert" className="grid min-h-dvh place-items-center bg-background p-6 text-foreground">
        <div className="w-full max-w-md space-y-4 rounded-lg border border-border-strong bg-surface-1 p-6">
          <div className="flex items-center gap-2 text-loss">
            <AlertTriangle className="size-5" aria-hidden />
            <h1 className="text-lg font-semibold">The control panel hit an error</h1>
          </div>
          <p className="text-sm text-secondary-foreground">
            The GUI stopped rendering. The trading engine runs as a separate process and is
            unaffected — open positions continue to be managed by the bot.
          </p>
          <p className="break-words font-mono text-xs text-muted-foreground">{error.message}</p>
          <Button onClick={() => window.location.reload()}>Reload the panel</Button>
        </div>
      </div>
    );
  }
}
