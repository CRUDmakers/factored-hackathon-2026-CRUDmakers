import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import AuthLayout from "./layouts/auth/auth-layout";
import { lazy } from "react";
import { App } from "./App";

const SignInPage = lazy(() => import("./pages/auth/sign-in/sign-in"));

export default function AppRouter() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="*" element={<div>Not found</div>} />
                <Route path="/" element={<Navigate to="/auth/sign-in" />} />

                <Route path="/auth" element={<AuthLayout children={<Outlet />} />}>
                    <Route path="sign-in" element={<SignInPage />} />
                    <Route path="sign-up" />
                    <Route path="forgot-password" />
                    <Route path="reset-password" />
                </Route>

                <Route path="/app" element={<App />} />
            </Routes>
        </BrowserRouter>
    );
}
