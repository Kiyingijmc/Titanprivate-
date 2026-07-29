import { useCallback } from "react";
import { useReadOnly } from "../context/ReadOnlyContext";
import type { ApiError } from "./api";

function isApiError(e: unknown): e is ApiError {
  return typeof e === "object" && e !== null && "kind" in e;
}

export type MutateResult<T> = { ok: true; value: T } | { ok: false; error: string };

export function useMutate() {
  const { setReadOnly } = useReadOnly();

  const run = useCallback(
    async <T,>(fn: () => Promise<T>): Promise<MutateResult<T>> => {
      try {
        const value = await fn();
        return { ok: true, value };
      } catch (e) {
        if (isApiError(e) && e.kind === "readOnly") {
          setReadOnly(true);
          return { ok: false, error: "read-only" };
        }
        return { ok: false, error: isApiError(e) ? e.detail : "request failed" };
      }
    },
    [setReadOnly]
  );

  return { run };
}
