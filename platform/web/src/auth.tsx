import React, { createContext, useContext, useEffect, useState } from "react";
import { api, get, post, setToken, getToken } from "./api";

export type Me = {
  id: string; name: string; roles: string[]; permissions: string[]; customer_id?: string | null; owner_id?: string | null;
  vendor_id?: string | null; driver_id?: string | null; scope_trip_id?: string | null;
};
type Ctx = { me: Me | null; ready: boolean; can: (p: string) => boolean; login: (id: string, pw: string) => Promise<Me>; otpLogin: (phone: string, otp: string) => Promise<Me>; logout: () => void };
const AuthCtx = createContext<Ctx>(null as any);

export function homeFor(me: Me): string {
  if (me.customer_id) return "/portal/customer";
  if (me.owner_id) return "/portal/owner";
  if (me.vendor_id) return "/portal/vendor";
  if (me.driver_id && me.permissions.includes("driver.app") && me.permissions.length <= 4) return "/driver";
  return "/erp";
}

export function AuthProvider({ children }: { children: React.ReactNode }) {
  const [me, setMe] = useState<Me | null>(null);
  const [ready, setReady] = useState(false);
  useEffect(() => {
    if (getToken()) get<Me>("/auth/me").then(setMe).catch(() => setToken(null)).finally(() => setReady(true));
    else setReady(true);
    const out = () => setMe(null);
    window.addEventListener("grl:logout", out);
    return () => window.removeEventListener("grl:logout", out);
  }, []);
  const login = async (identifier: string, password: string) => {
    const r = await post<{ token: string; user: Me }>("/auth/login", { identifier, password, device: navigator.userAgent.slice(0, 150) });
    setToken(r.token);
    setMe(r.user);
    return r.user;
  };
  const otpLogin = async (phone: string, otp: string) => {
    const r = await post<{ token: string; user: Me }>("/auth/otp/verify", { phone, otp, device: navigator.userAgent.slice(0, 150) });
    setToken(r.token);
    setMe(r.user);
    return r.user;
  };
  const logout = () => {
    api("/auth/logout", { method: "POST", body: {} }).catch(() => {});
    setToken(null);
    setMe(null);
  };
  const can = (p: string) => !!me?.permissions.includes(p);
  return <AuthCtx.Provider value={{ me, ready, can, login, otpLogin, logout }}>{children}</AuthCtx.Provider>;
}
export const useAuth = () => useContext(AuthCtx);
