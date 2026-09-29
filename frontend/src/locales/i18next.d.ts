import auth from "./pt/auth.json";
import commom from "./pt/common.json";

import { defaultNS } from "./i18n";

export const resources = {
    pt: { common, auth },
};

declare module "i18next" {
    interface CustomTypeOptions {
        defaultNS: typeof defaultNS;
        resources: (typeof resources)["pt"];
    }
}
