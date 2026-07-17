"""settings.html translations."""

NL = {
    "settings.title": "Instellingen",

    "settings.notice_saved": "✓ Instellingen opgeslagen.",
    "settings.notice_deleted_transactions": "✓ Alle transacties, koersen en cash-events verwijderd.",
    "settings.notice_deleted_all": "✓ Alle data verwijderd. Je kunt opnieuw beginnen.",
    "settings.notice_classified": "✓ {count} instrument(en) bijgewerkt.",

    # ── Quick links ────────────────────────────────────────────────────
    "settings.quicklink_accounts": "Accounts",
    "settings.quicklink_import": "Importeren",

    # ── General settings ──────────────────────────────────────────────
    "settings.section_logo": "Bedrijfslogo API keys",
    "settings.label_logo_dev_key": "Logo.dev publishable key (optioneel)",
    "settings.logo_dev_key_hint": "Laat leeg om de bestaande sleutel te behouden.",
    "settings.logo_dev_key_info": "Maak een gratis account op Logo.dev, open het dashboard en kopieer daar je publishable key (pk_…).",
    "settings.logo_dev_key_configured": "Actief",
    "settings.clear_logo_dev_key": "Logo-sleutel verwijderen",

    # ── YubiKeys / security keys ──────────────────────────────────────
    "settings.section_yubikeys": "YubiKeys / beveiligingssleutels",
    "settings.yubikeys_intro": "Voeg een extra sleutel toe als back-up, of om vanaf een andere plek te kunnen inloggen.",
    "settings.col_name": "Naam",
    "settings.col_added": "Toegevoegd",
    "settings.key_default_name": "Sleutel {id}",
    "settings.rename_key_aria": "Naam van sleutel {id}",
    "settings.btn_rename": "Hernoemen",
    "settings.confirm_delete_key": "Deze sleutel verwijderen? Je kunt er dan niet meer mee inloggen.",
    "settings.btn_delete": "✕ Verwijderen",
    "settings.last_key_hint": "Je kunt de laatste sleutel niet verwijderen",
    "settings.yk_name_label": "Naam voor nieuwe sleutel (optioneel)",
    "settings.yk_name_placeholder": "bijv. Backup YubiKey",
    "settings.yk_add_btn": "🔑 Nieuwe YubiKey toevoegen",

    # ── Database info & backup ────────────────────────────────────────
    "settings.section_database": "Database",
    "settings.db_transactions": "transacties",
    "settings.db_instruments": "instrumenten",
    "settings.db_accounts": "accounts",
    "settings.download_backup": "⬇ Database downloaden",

    # ── Danger zone ────────────────────────────────────────────────────
    "settings.section_danger": "⚠ Data verwijderen",
    "settings.danger_intro": "Gebruik dit als je opnieuw wilt beginnen of als de import fout gegaan is. Accounts en instellingen blijven bewaard bij \"transacties verwijderen\".",
    "settings.confirm_delete_txn": "Alle transacties, koersen en events verwijderen? Dit kan niet ongedaan worden.",
    "settings.btn_delete_txn": "🗑 Transacties & koersen verwijderen",
    "settings.confirm_delete_all": "ALLES verwijderen inclusief accounts en instrumenten? Dit kan niet ongedaan worden.",
    "settings.btn_delete_all": "💥 Alles verwijderen (volledige reset)",

    # ── Ticker mapping overview ───────────────────────────────────────
    "settings.section_ticker_mapping": "Tickerkoppelingen ({count} gemapped)",
    "settings.ticker_mapping_intro1": "Klik op een instrument om de ticker handmatig aan te passen. Gebruik \"Reset\" als een ticker fout is (bijv.",
    "settings.ticker_mapping_intro2": ") en herstart daarna automatisch toewijzen via de",
    "settings.import_page_link": "importpagina",
    "settings.col_isin": "ISIN",
    "settings.col_ticker": "Ticker",
    "settings.btn_reset": "✕ Reset",
    "settings.confirm_reset_one_ticker": "Ticker {symbol} wissen voor {name}?",
    "settings.confirm_reset_all_tickers": "Alle {count} tickers wissen? Auto-map opnieuw uitvoeren daarna.",
    "settings.btn_reset_all_tickers": "🔄 Reset alle tickers ({count})",
    "settings.btn_refresh_classifications": "🏷 Sector/regio + ETF-gegevens vernieuwen",
    "settings.refresh_classifications_hint": "Vult alleen lege sector/regio-velden aan (handmatige aanpassingen blijven staan) en haalt voor ETF's/fondsen de samenstelling op (top holdings, sectorverdeling, asset classes) — te zien op de instrumentpagina, en gebruikt voor een nauwkeurigere sectorgrafiek i.p.v. \"Unclassified\".",
    "settings.no_tickers_mapped": "Geen tickers gemapped. Gebruik",
    "settings.auto_map_link": "auto-toewijzen",

    # ── Unmapped instruments ──────────────────────────────────────────
    "settings.section_unmapped": "Instrumenten zonder tickerkoppeling ({count})",
    "settings.unmapped_intro1": "Wijs een yfinance ticker toe zodat live koersen opgehaald kunnen worden. Ga naar de",
    "settings.unmapped_intro2": "voor een overzichtstabel, of klik op een instrument hieronder.",
    "settings.more_prefix": "… en nog {count} meer (zie",

    # ── JS: add-YubiKey flow ──────────────────────────────────────────
    "settings.js_https_required": "✗ WebAuthn werkt alleen via HTTPS (of localhost).",
    "settings.js_connecting": "Verbinden met server…",
    "settings.js_touch_key": "Raak je YubiKey aan…",
    "settings.js_key_added": "✓ Sleutel toegevoegd. Pagina wordt vernieuwd…",
    "settings.js_error_prefix": "✗ Fout: ",
}

EN = {
    "settings.title": "Settings",

    "settings.notice_saved": "✓ Settings saved.",
    "settings.notice_deleted_transactions": "✓ All transactions, prices and cash events deleted.",
    "settings.notice_deleted_all": "✓ All data deleted. You can start over.",
    "settings.notice_classified": "✓ {count} instrument(s) updated.",

    "settings.quicklink_accounts": "Accounts",
    "settings.quicklink_import": "Import",

    "settings.section_logo": "Company logo API keys",
    "settings.label_logo_dev_key": "Logo.dev publishable key (optional)",
    "settings.logo_dev_key_hint": "Leave empty to keep the existing key.",
    "settings.logo_dev_key_info": "Create a free Logo.dev account, open the dashboard and copy your publishable key (pk_…).",
    "settings.logo_dev_key_configured": "Active",
    "settings.clear_logo_dev_key": "Remove logo key",

    "settings.section_yubikeys": "YubiKeys / security keys",
    "settings.yubikeys_intro": "Add an extra key as a backup, or to be able to log in from another location.",
    "settings.col_name": "Name",
    "settings.col_added": "Added",
    "settings.key_default_name": "Key {id}",
    "settings.rename_key_aria": "Name of key {id}",
    "settings.btn_rename": "Rename",
    "settings.confirm_delete_key": "Delete this key? You will no longer be able to log in with it.",
    "settings.btn_delete": "✕ Delete",
    "settings.last_key_hint": "You cannot delete the last key",
    "settings.yk_name_label": "Name for new key (optional)",
    "settings.yk_name_placeholder": "e.g. Backup YubiKey",
    "settings.yk_add_btn": "🔑 Add new YubiKey",

    "settings.section_database": "Database",
    "settings.db_transactions": "transactions",
    "settings.db_instruments": "instruments",
    "settings.db_accounts": "accounts",
    "settings.download_backup": "⬇ Download database",

    "settings.section_danger": "⚠ Delete data",
    "settings.danger_intro": "Use this if you want to start over or if the import went wrong. Accounts and settings are kept when using \"delete transactions\".",
    "settings.confirm_delete_txn": "Delete all transactions, prices and events? This cannot be undone.",
    "settings.btn_delete_txn": "🗑 Delete transactions & prices",
    "settings.confirm_delete_all": "Delete EVERYTHING including accounts and instruments? This cannot be undone.",
    "settings.btn_delete_all": "💥 Delete everything (full reset)",

    "settings.section_ticker_mapping": "Ticker mappings ({count} mapped)",
    "settings.ticker_mapping_intro1": "Click on an instrument to manually adjust the ticker. Use \"Reset\" if a ticker is wrong (e.g.",
    "settings.ticker_mapping_intro2": ") and then restart automatic assignment via the",
    "settings.import_page_link": "import page",
    "settings.col_isin": "ISIN",
    "settings.col_ticker": "Ticker",
    "settings.btn_reset": "✕ Reset",
    "settings.confirm_reset_one_ticker": "Clear ticker {symbol} for {name}?",
    "settings.confirm_reset_all_tickers": "Clear all {count} tickers? Auto-map will run again afterwards.",
    "settings.btn_reset_all_tickers": "🔄 Reset all tickers ({count})",
    "settings.btn_refresh_classifications": "🏷 Refresh sector/region + ETF data",
    "settings.refresh_classifications_hint": "Only fills empty sector/region fields (manual adjustments are kept) and fetches composition data for ETFs/funds (top holdings, sector breakdown, asset classes) — visible on the instrument page, and used for a more accurate sector chart instead of \"Unclassified\".",
    "settings.no_tickers_mapped": "No tickers mapped. Use",
    "settings.auto_map_link": "auto-assign",

    "settings.section_unmapped": "Instruments without ticker mapping ({count})",
    "settings.unmapped_intro1": "Assign a yfinance ticker so live prices can be fetched. Go to the",
    "settings.unmapped_intro2": "for an overview table, or click on an instrument below.",
    "settings.more_prefix": "… and {count} more (see",

    "settings.js_https_required": "✗ WebAuthn only works over HTTPS (or localhost).",
    "settings.js_connecting": "Connecting to server…",
    "settings.js_touch_key": "Touch your YubiKey…",
    "settings.js_key_added": "✓ Key added. Reloading page…",
    "settings.js_error_prefix": "✗ Error: ",
}
