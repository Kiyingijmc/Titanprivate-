import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";

/**
 * Access-token gate. `children` receives the confirmed token AND an `onInvalid`
 * callback: when the live layer discovers the token was rejected (WS close 1008
 * / REST 401), it calls onInvalid, which returns the user to this gate with a
 * message — instead of leaving them stranded on a "Reconnecting" shell with no
 * data and no way to re-enter the token.
 */
export function TokenGate({
  children,
}: {
  children: (token: string, onInvalid: (message?: string) => void) => ReactNode;
}) {
  const [token, setToken] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  const [error, setError] = useState<string | null>(null);

  if (token) {
    return (
      <>
        {children(token, (message) => {
          setToken(null);
          setDraft("");
          setError(message ?? "Disconnected — please re-enter your access token.");
        })}
      </>
    );
  }

  const submit = () => {
    if (!draft) return;
    setError(null);
    setToken(draft);
  };

  return (
    <div className="min-h-dvh grid place-items-center">
      <Card className="p-6 w-80 space-y-4">
        <h1 className="font-mono text-lg">Titan Control</h1>
        <label className="block text-sm text-muted-foreground" htmlFor="token">
          Access token
        </label>
        <Input
          id="token"
          type="password"
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
        />
        {error && (
          <p role="alert" className="text-sm text-loss">
            {error}
          </p>
        )}
        <Button className="w-full" disabled={!draft} onClick={submit}>
          Connect
        </Button>
      </Card>
    </div>
  );
}
