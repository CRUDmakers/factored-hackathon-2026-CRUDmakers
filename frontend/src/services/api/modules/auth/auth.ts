import ApiModule from "../module";
import { AuthSignInBody, AuthSignInResponse } from "./types";

export default class AuthModule extends ApiModule {
    public async signIn(body: AuthSignInBody): Promise<AuthSignInResponse> {
        return await this.post<AuthSignInResponse>("/auth/sign-in", body);
    }
}
