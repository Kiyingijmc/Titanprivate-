import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Card } from "@/components/ui/card";

export function TokenGate({ children }: { children: (token: string) => ReactNode }) {
  const [token, setToken] = useState<string | null>(null);
  const [draft, setDraft] = useState("");
  if (token) return <>{children(token)}</>;
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
            if (e.key === "Enter" && draft) setToken(draft);
          }}
        />
        <Button className="w-full" disabled={!draft} onClick={() => setToken(draft)}>
          Connect
        </Button>
      </Card>
    </div>
  );
}
