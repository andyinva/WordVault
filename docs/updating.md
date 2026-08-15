# Getting Updates

First, the promise that makes updating fearless: **an update never
touches your writing.** Your library lives in your home folder
(`C:\Users\<you>\.wordvault\` on Windows, `~/.wordvault/` on Ubuntu)
— your documents, their whole history, your personal dictionary, and
your personal print formats. The program folder and the library are
different places; replacing the program leaves the library exactly as
it was. (A backup is still wisdom, not worry: Library ▸ Back Up
Library… before an update takes one minute.)

There are two ways to update, depending on how WordVault arrived.

## If you use GitHub Desktop (or git)

1. Close WordVault.
2. Open GitHub Desktop, choose the WordVault repository, and click
   **Fetch origin**, then **Pull origin** if it offers changes.
   (Plain git: `git pull` in the WordVault folder.)
3. Start WordVault again. Done.

If you have made your own local changes to the code, GitHub Desktop
will say so — commit or discard them before pulling.

## If you downloaded a ZIP

1. Close WordVault.
2. Download a fresh ZIP from the same place you got the first one
   (the green **Code** button ▸ Download ZIP).
3. Unzip it **over the old program folder**, replacing the program's
   files — or unzip to a new folder and delete the old one. Your
   library is not in there, so nothing of yours is at risk.
4. Start WordVault again.

## After updating — usually nothing

- **Print formats**: shipped formats you never edited upgrade
  themselves on the next start; any format you edited is yours
  forever and is never overwritten.
- **The library**: opens as always. New features simply appear.
- **New requirements** are rare; if a new feature needs a package,
  its error message says exactly what to run (for example
  `pip install qrcode` for the copyright-page QR code).
- **The cautious ritual** (optional): run `python -m pytest` in the
  program folder — a few seconds, all green means your machine and
  the new version agree. The window title shows the version and its
  date, so you can confirm what you are running.

## If something seems wrong after an update

Your writing is safe — the library was not part of the update. Close
WordVault, and either pull again / re-download (a fresh copy fixes a
half-finished update), or go back one version in GitHub Desktop
(History ▸ right-click a commit ▸ revert). The library works with the
version that made it and with every later one.
