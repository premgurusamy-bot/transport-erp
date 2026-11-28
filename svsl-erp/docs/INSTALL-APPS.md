# Install as apps (Windows installer + Android APK)

Both files are built automatically by GitHub Actions and published on the repository's **Releases** page
(`A Prime Transport ERP build N`).

## 1. Main office computer – `A-Prime-Transport-ERP-Setup-1.0.0.exe`

1. Download and run the installer (Windows 10/11, 64-bit). If Windows SmartScreen warns "unknown publisher"
   (the installer is not code-signed), click **More info → Run anyway**.
2. Open **A Prime Transport ERP** from the desktop. Choose **This computer is the main ERP computer** → *Continue*.
   The first start creates the database (about a minute).
3. The **first-time setup** screen opens: enter the company name, state, GSTIN, address and phone, then create the
   administrator login (your name, a username and a password). Tick *Fill with DEMO data* only for a training copy.
   A **15-day free trial** starts; see *Licence* below.
4. **File → Save security keys…** and keep that file safely with your backups (needed to restore on a new PC).
5. **Help → Phone connection** shows the address phones must use, e.g. `192.168.1.20:8000`.

Nothing else needs to be installed: the database (PostgreSQL 16) and the ERP server are inside the installer.
Data: `%LOCALAPPDATA%\A Prime Transport ERP\Database` · documents and backups: `Documents\A Prime Transport ERP`
(computers installed before the rename keep using their `SVL ERP` folders). Uninstalling the app does not delete data. Keep this computer switched on (and A Prime Transport ERP open) while others use the ERP.

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

## Licence (trial and subscription)

* Every new installation runs free for **15 days**. A blue strip at the top shows the days left.
* To continue, open **Admin → Licence**, send the **Installation ID** shown there to your A Prime Transport ERP
  provider, and paste the licence key you receive into *Enter a licence key* → **Activate**. No internet is needed.
* Plans: monthly, quarterly, half-yearly or yearly subscription, or a lifetime licence. A key can limit the number of
  staff users (customer-portal and driver-app logins are not counted).
* When a subscription ends there are **7 more days** to renew. After that the ERP is **read-only**: everything can be
  viewed, searched, printed, exported and backed up, but nothing new can be entered until a renewal key is activated.
  No data is ever deleted.
* Phones and other office computers use the main computer's licence – nothing to enter on them.
