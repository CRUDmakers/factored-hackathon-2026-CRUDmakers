import { endSession, getSession, startSession } from "@/api";
import AuthModule from "./auth";

/** Delegates to api.ts, which owns the token (the AI backend reuses the same one). */
export default class RealAuthModule extends AuthModule {
    public async login(body: { customerId: string }): Promise<void> {
        await startSession(body.customerId);
    }

    public async logout(): Promise<void> {
        await endSession();
    }

    public async getSession(): Promise<{ customerId: string } | null> {
        return getSession();
    }
}
