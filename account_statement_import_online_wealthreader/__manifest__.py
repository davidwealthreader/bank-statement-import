# Copyright 2026 Wealth Reader
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
{
    "name": "Online Bank Statements: Wealth Reader",
    "version": "18.0.1.0.0",
    "category": "Account",
    "website": "https://github.com/OCA/bank-statement-import",
    "author": "Wealth Reader, Odoo Community Association (OCA)",
    "license": "AGPL-3",
    "installable": True,
    "depends": [
        "account_statement_import_online",
    ],
    "data": [
        "view/online_bank_statement_provider.xml",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
}
