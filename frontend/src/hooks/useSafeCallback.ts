import useSystem from "@/contexts/system/use-system";
import { useCallback } from "react";

export default function useSafeCallback<Args, R>(fn: (args: Args) => Promise<R>, deps: unknown[]) {
    const { showAlert } = useSystem();

    return useCallback(async (args: Args) => {
        try {
            await fn(args);
        } catch (err) {
            if (err instanceof AbortSignal) return;
            if (err instanceof Error) showAlert(err.message, "error");
            else showAlert("An unexpected error occurred.", "error");
        }
    }, deps);
}
