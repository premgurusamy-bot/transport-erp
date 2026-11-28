# Issuing licences (software provider only)

Licence keys are made with **A-Prime-Licence-Manager.html**, a single file that contains your private signing key.
It is *not* in this repository and must never be uploaded, e-mailed to customers or shared: anyone holding it can
make keys. Keep two copies (e.g. a pen drive and a private cloud folder). If it is lost, new keys cannot be made for
installations that check the current public key (a new key pair can be added to `PUBLIC_KEYS` in
`backend/app/services/licensing.py` in a new version; older keys keep working).

## Issue a key

1. The customer installs the ERP (15-day trial starts) and sends you the **Installation ID** from *Admin → Licence*,
   e.g. `5EE8-476B-758B-555D`, and their company name.
2. Open A-Prime-Licence-Manager.html in Google Chrome or Microsoft Edge (double-click; it works offline, also on an
   Android phone with Chrome).
3. Enter the company name and installation ID, choose the plan (monthly / quarterly / half-yearly / yearly /
   lifetime / trial extension), the start date, number of staff users and a note (amount received).
4. **Create licence key** → *Copy key*, *Save as .txt* or *Share on WhatsApp*. The customer pastes it in
   *Admin → Licence → Activate*.
5. Each key is listed in *Issued licences* in that browser. Use **Export register (CSV)** regularly.

Renewal: issue a new key for the same installation ID starting the day after the old one ends.
A new computer for the same customer has a new installation ID – issue a new key (and stop renewing the old one).
"Works on any installation" (`*`) is only for a cloud server you run yourself.

Command-line alternative: `python scripts/issue_licence.py --key-file <signing key> --to "…" --iid XXXX-XXXX-XXXX-XXXX --plan yearly --users 10`.

## How it is protected (and its limits)

* Keys are Ed25519-signed; changing any detail (dates, users, name) makes the key invalid.
* A key works only on the installation ID it names (derived from the Windows machine ID).
* The trial start date is kept both in the database and in `%PROGRAMDATA%\A Prime Transport ERP\Licence`, so
  reinstalling or a factory reset does not restart the trial. Setting the computer clock back by more than two days
  makes the ERP read-only until the clock is corrected.
* Like all offline licensing, it stops honest over-use and casual copying; a determined technical person could still
  modify the program. Keep the source code private.
