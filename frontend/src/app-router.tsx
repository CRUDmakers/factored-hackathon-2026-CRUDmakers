import { BrowserRouter, Navigate, Outlet, Route, Routes } from "react-router-dom";
import { lazy } from "react";

import SessionProvider from "./contexts/session/session-provider";

import AuthLayout from "./layouts/auth/auth-layout";
import SessionLayout from "./layouts/session/session-layout";

const LoginPage = lazy(() => import("./pages/auth/login/login-page"));

const HomePage = lazy(() => import("./pages/session/home/home-page"));

import { Exchange } from "./pages/Exchange";
import { Home } from "./pages/Home";
import { Pay } from "./pages/Pay";
import { Login } from "./pages/Login";
import { Reports } from "./pages/Reports";
import { Schedules } from "./pages/Schedules";
import { Statement } from "./pages/Statement";

export default function AppRouter() {
    return (
        <BrowserRouter>
            <Routes>
                <Route path="*" element={<div>Not found</div>} />
                <Route path="/" element={<Navigate to="/auth/sign-in" />} />

                <Route path="/auth" element={<AuthLayout children={<Outlet />} />}>
                    <Route path="sign-in" element={<LoginPage />} />
                    <Route path="sign-up" />
                    <Route path="forgot-password" />
                    <Route path="reset-password" />
                </Route>

                <Route path="/session" element={<SessionProvider children={<SessionLayout />} />}>
                    <Route path="home" element={<HomePage />} />
                </Route>

                <Route path="/app" element={<Outlet />}>
                    <Route path="exchange" element={<Exchange />} />
                    <Route path="home" element={<Home />} />
                    <Route path="login" element={<Login />} />
                    <Route path="pay" element={<Pay />} />
                    <Route path="reports" element={<Reports />} />
                    <Route path="schedules" element={<Schedules />} />
                    <Route path="statement" element={<Statement />} />
                </Route>
            </Routes>
        </BrowserRouter>
    );
}
