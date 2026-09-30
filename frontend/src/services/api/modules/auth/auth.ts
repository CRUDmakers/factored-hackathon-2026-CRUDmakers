import ApiModule from "../module";

export default abstract class AuthModule extends ApiModule {
    abstract login(body: { customerId: string }): Promise<void>;

    abstract logout(): Promise<void>;

    abstract getSession(): Promise<{ customerId: string }>;
}
