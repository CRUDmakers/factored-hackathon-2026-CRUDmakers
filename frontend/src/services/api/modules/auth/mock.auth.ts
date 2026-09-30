import AuthModule from "./auth";

export default class MockAuthModule extends AuthModule {
    public async login(body: { customerId: string }): Promise<void> {
        console.log(`Fake login with customerId: ${body.customerId}`);
        await this.sleep(500);
    }

    public async logout(): Promise<void> {
        console.log("Fake logout");
        await this.sleep(500);
    }

    public async getSession(): Promise<{ customerId: string }> {
        await this.sleep(500);
        return { customerId: "fake-customer-id" };
    }
}
