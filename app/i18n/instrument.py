"""instrument.html translations."""

NL = {
    # Position summary stat cards
    "instrument.stat_quantity": "Aantal:",
    "instrument.stat_avg_cost": "Gem. kosten:",
    "instrument.stat_value": "Waarde:",
    "instrument.stat_result": "Resultaat:",

    # Cached price
    "instrument.price_label": "Koers:",
    "instrument.price_converted": "(omgerekend van {currency} naar EUR)",

    # Fund composition
    "instrument.fund_composition": "Fondssamenstelling",
    "instrument.fund_updated": "bijgewerkt {date}",
    "instrument.asset_classes_label": "Asset classes:",
    "instrument.sector_breakdown": "Sectorverdeling",
    "instrument.top_holdings": "Top holdings",

    # Manual country allocation
    "instrument.country_weight_title": "Landenweging",
    "instrument.country_weight_hint": "handmatig; gebruikt voor de continentgrafiek",
    "instrument.country_weight_total": "Totaal: {total}%",
    "instrument.country_weight_error_invalid": "Vul een land en een percentage groter dan 0 en maximaal 100 in.",
    "instrument.country_weight_error_total": "De landenwegingen mogen samen niet boven 100% uitkomen.",
    "instrument.col_country": "Land",
    "instrument.col_weight": "Weging",
    "instrument.btn_delete": "Verwijder",
    "instrument.country_placeholder": "Land, bijv. Verenigde Staten",
    "instrument.weight_placeholder": "Weging (%)",
    "instrument.btn_add": "Toevoegen",

    # Edit form
    "instrument.edit_title": "Aanpassen",
    "instrument.field_ticker": "yfinance ticker",
    "instrument.ticker_placeholder": "bijv. VWRL.AS",
    "instrument.field_region": "Regio",
    "instrument.field_manual_div": "Jaarlijks dividend/aandeel (€, handmatig)",
    "instrument.manual_div_placeholder": "bijv. 2.50",
    "instrument.btn_fetch_metadata": "Metadata ophalen",

    # Manual transaction entry
    "instrument.manual_txn_summary": "Handmatige transactie invoeren (corporate actions, correcties)",
    "instrument.manual_txn_hint": "Gebruik dit voor split-aanpassingen, fusies of andere corporate actions die niet automatisch worden verwerkt. Selecteer \"Verkoop\" om een positie te sluiten.",
    "instrument.field_direction": "Richting",
    "instrument.direction_buy": "Koop / Ontvangen",
    "instrument.direction_sell": "Verkoop / Sluiten",
    "instrument.col_quantity": "Aantal",
    "instrument.quantity_placeholder": "bijv. 10",
    "instrument.col_price": "Koers",
    "instrument.txn_price_placeholder": "bijv. 47,73",
    "instrument.field_note": "Opmerking (optioneel)",
    "instrument.note_placeholder": "bijv. split aanpassing dec 2025",
    "instrument.btn_add_transaction": "Transactie toevoegen",

    # Manual price entry
    "instrument.manual_price_summary": "Handmatige koers invoeren",
    "instrument.manual_price_placeholder": "bijv. 118,50",
    "instrument.field_currency": "Valuta",

    # Transaction history
    "instrument.transactions_title": "Transacties",
    "instrument.col_value_eur": "Waarde (€)",
    "instrument.col_fees_eur": "Kosten (€)",
    "instrument.no_transactions": "Geen transacties.",

    # Dividend history
    "instrument.col_dividend_type": "Type",

    # JS strings
    "instrument.js_txn_added": "Transactie toegevoegd",
    "instrument.js_price_saved": "Koers opgeslagen",
    "instrument.js_error_prefix": "Fout: ",
    "instrument.js_error_unknown": "onbekend",
}

EN = {
    # Position summary stat cards
    "instrument.stat_quantity": "Quantity:",
    "instrument.stat_avg_cost": "Avg. cost:",
    "instrument.stat_value": "Value:",
    "instrument.stat_result": "Result:",

    # Cached price
    "instrument.price_label": "Price:",
    "instrument.price_converted": "(converted from {currency} to EUR)",

    # Fund composition
    "instrument.fund_composition": "Fund composition",
    "instrument.fund_updated": "updated {date}",
    "instrument.asset_classes_label": "Asset classes:",
    "instrument.sector_breakdown": "Sector breakdown",
    "instrument.top_holdings": "Top holdings",

    # Manual country allocation
    "instrument.country_weight_title": "Country allocation",
    "instrument.country_weight_hint": "manual; used for the continent chart",
    "instrument.country_weight_total": "Total: {total}%",
    "instrument.country_weight_error_invalid": "Enter a country and a percentage greater than 0 and at most 100.",
    "instrument.country_weight_error_total": "Country allocations may not add up to more than 100%.",
    "instrument.col_country": "Country",
    "instrument.col_weight": "Weight",
    "instrument.btn_delete": "Delete",
    "instrument.country_placeholder": "Country, e.g. United States",
    "instrument.weight_placeholder": "Weight (%)",
    "instrument.btn_add": "Add",

    # Edit form
    "instrument.edit_title": "Edit",
    "instrument.field_ticker": "yfinance ticker",
    "instrument.ticker_placeholder": "e.g. VWRL.AS",
    "instrument.field_region": "Region",
    "instrument.field_manual_div": "Annual dividend/share (€, manual)",
    "instrument.manual_div_placeholder": "e.g. 2.50",
    "instrument.btn_fetch_metadata": "Fetch metadata",

    # Manual transaction entry
    "instrument.manual_txn_summary": "Enter manual transaction (corporate actions, corrections)",
    "instrument.manual_txn_hint": "Use this for split adjustments, mergers, or other corporate actions that aren't processed automatically. Select \"Sell\" to close a position.",
    "instrument.field_direction": "Direction",
    "instrument.direction_buy": "Buy / Receive",
    "instrument.direction_sell": "Sell / Close",
    "instrument.col_quantity": "Quantity",
    "instrument.quantity_placeholder": "e.g. 10",
    "instrument.col_price": "Price",
    "instrument.txn_price_placeholder": "e.g. 47.73",
    "instrument.field_note": "Note (optional)",
    "instrument.note_placeholder": "e.g. split adjustment Dec 2025",
    "instrument.btn_add_transaction": "Add transaction",

    # Manual price entry
    "instrument.manual_price_summary": "Enter manual price",
    "instrument.manual_price_placeholder": "e.g. 118.50",
    "instrument.field_currency": "Currency",

    # Transaction history
    "instrument.transactions_title": "Transactions",
    "instrument.col_value_eur": "Value (€)",
    "instrument.col_fees_eur": "Fees (€)",
    "instrument.no_transactions": "No transactions.",

    # Dividend history
    "instrument.col_dividend_type": "Type",

    # JS strings
    "instrument.js_txn_added": "Transaction added",
    "instrument.js_price_saved": "Price saved",
    "instrument.js_error_prefix": "Error: ",
    "instrument.js_error_unknown": "unknown",
}
