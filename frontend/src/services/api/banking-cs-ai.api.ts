import MockAuthModule from "./modules/auth/mock.auth";
import RealAuthModule from "./modules/auth/real.auth";
import ApiModule from "./modules/module";

const BASE_URL = import.meta.env.VITE_API_URL;
const USE_MOCK_API = import.meta.env.VITE_USE_MOCK_API === "true";

function createModule<T extends ApiModule>(
    realModule: new (baseUrl: string) => T,
    mockModule: new (baseUrl: string) => T
): T {
    return USE_MOCK_API ? new mockModule(BASE_URL) : new realModule(BASE_URL);
}

const bankingCsAiApi = {
    auth: createModule(RealAuthModule, MockAuthModule),
};

export default bankingCsAiApi;
