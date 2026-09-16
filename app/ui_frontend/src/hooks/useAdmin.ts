import { useEffect, useState } from "react";
import { ADMIN_TOKEN_KEY } from "../lib/storage";

export const ADMIN_EVENT = "insidertrack:admin";

/** Call after admin login/logout so every page re-evaluates what to show. */
export function notifyAdminChange() {
  window.dispatchEvent(new Event(ADMIN_EVENT));
}

const read = () => {
  try { return sessionStorage.getItem(ADMIN_TOKEN_KEY) === "1"; } catch { return false; }
};

/**
 * True when this tab has signed in as admin. The real credential is an
 * httpOnly cookie; this flag only decides whether admin-only controls
 * (sync, edit, delete, add) are rendered at all.
 */
export default function useAdmin(): boolean {
  const [isAdmin, setIsAdmin] = useState<boolean>(read);
  useEffect(() => {
    const h = () => setIsAdmin(read());
    window.addEventListener(ADMIN_EVENT, h);
    window.addEventListener("storage", h);
    return () => { window.removeEventListener(ADMIN_EVENT, h); window.removeEventListener("storage", h); };
  }, []);
  return isAdmin;
}
