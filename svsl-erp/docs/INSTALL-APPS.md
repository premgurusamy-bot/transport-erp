# Install as apps (Windows installer + Android APK)

Both files are built automatically by GitHub Actions and published on the repository's **Releases** page
(`A Prime Transport ERP build N`).

## 1. Main office computer – `A-Prime-Transport-ERP-Setup-1.0.0.exe`

1. Download and run the installer (Windows 10/11, 64-bit). If Windows SmartScreen warns "unknown publisher"
   (the installer is not code-signed), click **More info → Run anyway**.
2. Open **A Prime Transport ERP** from the desktop. Choose **This computer is the main ERP computer** → *Continue*.
   The first start creates the database (about a minute).
3. A box shows the **admin password** once – write it down (or press *Copy password*). Sign in as `admin` and choose
   your own password.
4. **File → Save security keys…** and keep that file safely with your backups (needed to restore on a new PC).
5. **Help → Phone connection** shows the address phones must use, e.g. `192.168.1.20:8000`.

Nothing else needs to be installed: the database (PostgreSQL 16) and the ERP server are inside the installer.
Data: `%LOCALAPPDATA%\SVL ERP\Database` · documents and backups: `Documents\SVL ERP`. Uninstalling the app does
not delete data. Keep this computer switched on (and A Prime Transport ERP open) while others use the ERP.

Other office computers: install the same file and choose **Connect to the ERP on another computer**, entering the
address from step 5.

## 2. Phones – `A-Prime-Transport-ERP.apk` (Android 7+)

1. Download the APK on the phone, open it and allow **Install unknown apps** for your browser/files app when asked.
2. Open **A Prime Transport ERP**, enter the address from the office computer (e.g. `192.168.1.20:8000`) → *Connect*.
   The phone must be on the office Wi-Fi (or use your internet address if the ERP is hosted online).
3. Sign in. Drivers see the driver app, customers the customer portal, staff the full ERP.
4. PDFs and Excel files are saved to **Downloads** (tap the notification to open). WhatsApp share opens WhatsApp.
   To change the server later: *Change server address* on the sign-in screen.

The APK is a debug-signed build for direct installation (not from the Play Store). For Play Store distribution,
create a release keystore and sign the release build.

## Using it outside the office

The office-computer setup works on the local network. For drivers on the road, either connect the office network
through a VPN, or host the ERP online (see DEPLOYMENT.md) and enter that `https://` address in the apps.
