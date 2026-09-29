import AuthModule from "./modules/auth/auth";

const BASE_URL = import.meta.env.VITE_API_BASE_URL;

const bankingCsAiApi = {
    auth: new AuthModule(BASE_URL),
};

export default bankingCsAiApi;
