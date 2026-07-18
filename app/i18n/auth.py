"""auth.html translations."""

NL = {
    "auth.login_page_title": "Inloggen – PortfolioManager",
    "auth.login_heading": "Inloggen",
    "auth.login_instructions": "Steek je YubiKey in en klik op de knop hieronder.",
    "auth.login_button": "🔑 Inloggen met YubiKey",
    "auth.https_required_html": (
        "✗ WebAuthn werkt alleen via HTTPS.<br>"
        "Open de app via je proxy-domein (bijv. <code>https://portfolio.lan</code>), "
        "niet rechtstreeks via het IP-adres of HTTP."
    ),
    "auth.connecting": "Verbinden met server…",
    "auth.touch_key": "Raak je YubiKey aan…",
    "auth.login_success": "✓ Ingelogd! Doorsturen…",
    "auth.error_prefix": "✗ Fout: ",
    "auth.register_page_title": "YubiKey registreren – PortfolioManager",
    "auth.register_heading": "YubiKey instellen",
    "auth.register_instructions_line1": "Registreer je YubiKey voor toegang tot de applicatie.",
    "auth.setup_token_label": "Installatiecode",
    "auth.setup_token_help": "Gebruik de eenmalige code uit de serverlog, of de waarde van PM_SETUP_TOKEN.",
    "auth.setup_token_required": "✗ Vul eerst de installatiecode in.",
    "auth.register_button": "🔑 YubiKey registreren",
    "auth.no_yubikey_summary": "Heb je geen YubiKey?",
    "auth.no_yubikey_detail": (
        "Je kunt ook een andere FIDO2/WebAuthn-authenticator gebruiken "
        "(Android fingerprint, Windows Hello, enz.)."
    ),
    "auth.register_success": "✓ YubiKey geregistreerd! Doorsturen naar login…",
}

EN = {
    "auth.login_page_title": "Login – PortfolioManager",
    "auth.login_heading": "Login",
    "auth.login_instructions": "Insert your YubiKey and click the button below.",
    "auth.login_button": "🔑 Login with YubiKey",
    "auth.https_required_html": (
        "✗ WebAuthn only works over HTTPS.<br>"
        "Open the app via your proxy domain (e.g. <code>https://portfolio.lan</code>), "
        "not directly via the IP address or HTTP."
    ),
    "auth.connecting": "Connecting to server…",
    "auth.touch_key": "Touch your YubiKey…",
    "auth.login_success": "✓ Logged in! Redirecting…",
    "auth.error_prefix": "✗ Error: ",
    "auth.register_page_title": "YubiKey registration – PortfolioManager",
    "auth.register_heading": "Set up YubiKey",
    "auth.register_instructions_line1": "Register your YubiKey for access to the application.",
    "auth.setup_token_label": "Setup token",
    "auth.setup_token_help": "Use the one-time code from the server log, or the value of PM_SETUP_TOKEN.",
    "auth.setup_token_required": "✗ Enter the setup token first.",
    "auth.register_button": "🔑 Register YubiKey",
    "auth.no_yubikey_summary": "Don't have a YubiKey?",
    "auth.no_yubikey_detail": (
        "You can also use another FIDO2/WebAuthn authenticator "
        "(Android fingerprint, Windows Hello, etc.)."
    ),
    "auth.register_success": "✓ YubiKey registered! Redirecting to login…",
}
