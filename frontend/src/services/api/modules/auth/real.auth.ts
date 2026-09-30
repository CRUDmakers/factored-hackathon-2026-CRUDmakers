import AuthModule from "./auth";

export default class RealAuthModule extends AuthModule {
    public async login(body: { customerId: string }): Promise<void> {
        await this.post("/auth/test-session", { customer_id: body.customerId });
    }

    public async logout(): Promise<void> {
        await this.post("/auth/logout");
    }

    public async getSession(): Promise<{ customerId: string }> {
        const response = await fetch("/api/auth/session");
        return response.json();
    }
}
