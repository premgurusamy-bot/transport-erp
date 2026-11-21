// Detects the Android (Capacitor) and Windows (Electron) wrappers, which add a marker to the user agent.
export const isAndroidApp = /SVSLApp-Android/.test(navigator.userAgent);
export const isDesktopApp = /SVSLApp-Desktop/.test(navigator.userAgent);

/** Open an external link (WhatsApp, maps). Inside the Android app, hand WhatsApp links to the WhatsApp app. */
export function openExternal(url: string) {
  if (isAndroidApp) {
    const m = url.match(/^https:\/\/wa\.me\/(\d*)\?text=(.*)$/);
    location.href = m ? `whatsapp://send?${m[1] ? `phone=${m[1]}&` : ""}text=${m[2]}` : url;
    return;
  }
  window.open(url, "_blank");
}

/** Leave the ERP and return to the app's server-address screen (Android app only). */
export function changeServer() { location.href = "http://localhost/#change"; }
