import { createContext, useContext, useState, type ReactNode } from "react";

const Ctx = createContext<{ readOnly: boolean; setReadOnly: (v: boolean) => void } | null>(null);

export function ReadOnlyProvider({ children }: { children: ReactNode }) {
  const [readOnly, setReadOnly] = useState(false);
  return <Ctx.Provider value={{ readOnly, setReadOnly }}>{children}</Ctx.Provider>;
}

export function useReadOnly() {
  const v = useContext(Ctx);
  if (!v) throw new Error("useReadOnly outside provider");
  return v;
}
