# Copyright 2026 Wealth Reader
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from unittest.mock import patch

from odoo.tests.common import TransactionCase


class TestWealthReaderProvider(TransactionCase):
    def test_service_is_registered(self):
        services = dict(
            self.env["online.bank.statement.provider"]._get_available_services()
        )
        self.assertIn("wealthreader", services)

    def test_skips_non_numeric_amounts(self):
        provider = self.env["online.bank.statement.provider"].new(
            {
                "service": "wealthreader",
                "wealthreader_account_uuid": "acc-1",
            }
        )
        payload = {
            "payload": {
                "accounts": [
                    {
                        "uuid": "acc-1",
                        "transactions": [
                            {"uuid": "bad", "date": "2026-08-01", "amount": "n/a"},
                            {
                                "uuid": "ok",
                                "date": "2026-08-02",
                                "amount": "12.50",
                                "description": "Payroll",
                            },
                        ],
                    }
                ]
            }
        }
        with patch.object(type(provider), "_wealthreader_refresh", return_value=payload):
            lines, _extra = provider._wealthreader_obtain_statement_data(
                "2026-08-01", "2026-08-31"
            )
        self.assertEqual(len(lines), 1)
        self.assertEqual(lines[0]["unique_import_id"], "ok")
        self.assertEqual(lines[0]["amount"], 12.5)
