import useSystem from "@/contexts/system/use-system";
import { useCallback, useEffect, useState } from "react";

export function useAsync<T>(fn: (signal: AbortSignal) => Promise<T>, deps: unknown[]) {
    const { showAlert } = useSystem();

    const [state, setState] = useState<{ data?: T; error?: unknown; loading: boolean }>({ loading: true });

    const run = useCallback(fn, deps);

    const reload = useCallback(() => {
        const abortController = new AbortController();
        const signal = abortController.signal;

        let alive = true;
        setState((s) => ({ ...s, loading: true, error: undefined }));

        run(signal).then(
            (data) => alive && setState({ data, loading: false }),
            (error) => {
                if (!alive) return;
                if (signal?.aborted) return;
                alive && setState({ error, loading: false });

                if (error instanceof Error) return showAlert?.(error.message, "error");
                showAlert?.("An unexpected error occurred.", "error");
            }
        );
        return () => {
            alive = false;
            abortController.abort();
        };
    }, [run, showAlert]);

    useEffect(reload, [reload]);

    return { ...state, reload };
}
