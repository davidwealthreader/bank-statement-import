# Copyright 2025 Wealthreader
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

from datetime import datetime
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import common
from odoo.tools import mute_logger

MOCK_ENTITIES_RESPONSE = {
    "success": True,
    "payload": [
        {
            "accounts": [
                {
                    "uuid": "acc-uuid-001",
                    "code": "ES12 3456 7890 1234 5678 9012",
                    "name": "Current Account",
                    "currency": "EUR",
                    "subtype": "checking",
                    "balances": {
                        "available": 5000.00,
                        "current": 5200.50,
                    },
                    "transactions": [
                        {
                            "uuid": "tr-uuid-001",
                            "operation_date": "2024-01-15",
                            "value_date": "2024-01-15",
                            "amount": -150.00,
                            "balance": 5200.50,
                            "description": "Electricity bill payment",
                            "categorization": {"type": "utilities"},
                            "transfer_details": {
                                "concept": "Electricity Jan 2024",
                                "sender_receiver": "Electric Corp",
                                "account_number": "ES98 7654 3210 9876 5432 1098",
                            },
                        },
                        {
                            "uuid": "tr-uuid-002",
                            "operation_date": "2024-01-14",
                            "value_date": "2024-01-14",
                            "amount": 2500.00,
                            "balance": 5350.50,
                            "description": "Salary deposit",
                            "categorization": {"type": "income"},
                            "transfer_details": {
                                "concept": "January Salary",
                                "sender_receiver": "Employer Inc.",
                                "account_number": "ES11 2233 4455 6677 8899 0011",
                            },
                        },
                        {
                            "uuid": "tr-uuid-003",
                            "operation_date": "2024-01-10",
                            "value_date": "2024-01-12",
                            "amount": -45.99,
                            "balance": 2850.50,
                            "description": "Online purchase",
                            "transfer_details": {
                                "concept": "Order #12345",
                                "sender_receiver": "Online Shop SL",
                            },
                        },
                    ],
                }
            ],
        }
    ],
    "statistics": {
        "SESSION": "test-session-123",
        "execution_time": 3.5,
        "token": "tok_abc123",
    },
}

MOCK_EMPTY_RESPONSE = {
    "success": True,
    "payload": [{"accounts": []}],
    "statistics": {"SESSION": "test-session-456", "execution_time": 1.0},
}

MOCK_MULTI_ACCOUNT_RESPONSE = {
    "success": True,
    "payload": [
        {
            "accounts": [
                {
                    "uuid": "acc-uuid-001",
                    "code": "ES12 3456 7890 1234 5678 9012",
                    "name": "Current Account",
                    "currency": "EUR",
                    "balances": {"current": 5000.00},
                    "transactions": [],
                },
                {
                    "uuid": "acc-uuid-002",
                    "code": "ES99 8888 7777 6666 5555 4444",
                    "name": "Savings Account",
                    "currency": "EUR",
                    "balances": {"current": 15000.00},
                    "transactions": [],
                },
            ],
        }
    ],
    "statistics": {"SESSION": "test-session-789", "execution_time": 2.0},
}

MOCK_ERROR_RESPONSE = {
    "success": False,
    "error": {"code": 2001, "message": "Invalid credentials"},
    "statistics": {"SESSION": "test-session-err"},
}


class TestAccountStatementImportOnlineWealthreader(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.currency_eur = cls.env.ref("base.EUR")
        cls.bank_account = cls.env["res.partner.bank"].create(
            {
                "acc_number": "ES12 3456 7890 1234 5678 9012",
                "partner_id": cls.env.company.partner_id.id,
            }
        )
        cls.journal = cls.env["account.journal"].create(
            {
                "name": "Wealthreader Test Bank",
                "type": "bank",
                "code": "WRTS",
                "currency_id": cls.currency_eur.id,
                "bank_account_id": cls.bank_account.id,
            }
        )
        cls.provider = cls.env["online.bank.statement.provider"].create(
            {
                "journal_id": cls.journal.id,
                "service": "wealthreader",
                "password": "test_api_key",
                "username": "testuser",
                "key": "testpass",
                "wealthreader_entity_code": "testbank",
                "wealthreader_date_field": "value_date",
            }
        )

    def _mock_request(self, response_data):
        """Create a mock for requests.post that returns the given data."""

        class MockResponse:
            status_code = 200

            def json(self):
                return response_data

        return patch(
            "odoo.addons.account_statement_import_online_wealthreader"
            ".models.online_bank_statement_provider_wealthreader"
            ".requests.post",
            return_value=MockResponse(),
        )

    def test_get_available_services(self):
        """Wealthreader must be among available services."""
        services = self.provider._get_available_services()
        service_keys = [s[0] for s in services]
        self.assertIn("wealthreader", service_keys)

    def test_obtain_statement_data(self):
        """Standard transaction import with 3 lines."""
        date_since = datetime(2024, 1, 1)
        date_until = datetime(2024, 1, 31)
        with self._mock_request(MOCK_ENTITIES_RESPONSE):
            lines, statement = self.provider._obtain_statement_data(
                date_since, date_until
            )
        self.assertEqual(len(lines), 3)
        self.assertEqual(statement.get("balance_end_real"), 5200.50)
        # Token should have been persisted
        self.assertEqual(self.provider.wealthreader_token, "tok_abc123")
        # Account UUID should have been persisted
        self.assertEqual(self.provider.wealthreader_account_uuid, "acc-uuid-001")

    def test_transaction_fields(self):
        """Verify individual transaction field mapping."""
        date_since = datetime(2024, 1, 1)
        date_until = datetime(2024, 1, 31)
        with self._mock_request(MOCK_ENTITIES_RESPONSE):
            lines, _ = self.provider._obtain_statement_data(date_since, date_until)
        # First transaction: electricity bill
        line = lines[0]
        self.assertEqual(line["amount"], -150.00)
        self.assertEqual(line["payment_ref"], "Electricity Jan 2024")
        self.assertEqual(line["unique_import_id"], "WR-tr-uuid-001")
        self.assertEqual(line["partner_name"], "Electric Corp")
        self.assertEqual(line["account_number"], "ES98 7654 3210 9876 5432 1098")
        self.assertEqual(line["date"], "2024-01-15")

    def test_empty_response(self):
        """Empty accounts list returns empty data."""
        date_since = datetime(2024, 1, 1)
        date_until = datetime(2024, 1, 31)
        with self._mock_request(MOCK_EMPTY_RESPONSE):
            lines, statement = self.provider._obtain_statement_data(
                date_since, date_until
            )
        self.assertEqual(lines, [])
        self.assertEqual(statement, {})

    def test_multi_account_iban_match(self):
        """With multiple accounts, match by IBAN."""
        date_since = datetime(2024, 1, 1)
        date_until = datetime(2024, 1, 31)
        with self._mock_request(MOCK_MULTI_ACCOUNT_RESPONSE):
            lines, statement = self.provider._obtain_statement_data(
                date_since, date_until
            )
        # Should have matched the first account by IBAN
        self.assertEqual(self.provider.wealthreader_account_uuid, "acc-uuid-001")

    def test_multi_account_no_match_raises(self):
        """Multiple accounts without IBAN match raises UserError."""
        # Create a new bank account with a non-matching IBAN and a separate
        # journal/provider, because Odoo does not allow modifying acc_number
        # on a trusted bank account.
        other_bank_account = self.env["res.partner.bank"].create(
            {
                "acc_number": "XX00 0000 0000 0000 0000 0000",
                "partner_id": self.env.company.partner_id.id,
            }
        )
        other_journal = self.env["account.journal"].create(
            {
                "name": "Wealthreader No Match",
                "type": "bank",
                "code": "WRNM",
                "currency_id": self.currency_eur.id,
                "bank_account_id": other_bank_account.id,
            }
        )
        other_provider = self.env["online.bank.statement.provider"].create(
            {
                "journal_id": other_journal.id,
                "service": "wealthreader",
                "password": "test_api_key",
                "wealthreader_entity_code": "testbank",
            }
        )
        date_since = datetime(2024, 1, 1)
        date_until = datetime(2024, 1, 31)
        with self._mock_request(MOCK_MULTI_ACCOUNT_RESPONSE):
            with self.assertRaises(UserError):
                other_provider._obtain_statement_data(date_since, date_until)

    @mute_logger(
        "odoo.addons.account_statement_import_online_wealthreader"
        ".models.online_bank_statement_provider_wealthreader"
    )
    def test_api_error_raises(self):
        """API error responses are raised as UserError."""
        date_since = datetime(2024, 1, 1)
        date_until = datetime(2024, 1, 31)
        with self._mock_request(MOCK_ERROR_RESPONSE):
            with self.assertRaises(UserError):
                self.provider._obtain_statement_data(date_since, date_until)

    def test_missing_api_key_raises(self):
        """Missing API key raises UserError."""
        self.provider.password = False
        date_since = datetime(2024, 1, 1)
        date_until = datetime(2024, 1, 31)
        with self.assertRaises(UserError):
            self.provider._obtain_statement_data(date_since, date_until)

    def test_missing_entity_code_raises(self):
        """Missing entity code raises UserError."""
        self.provider.wealthreader_entity_code = False
        date_since = datetime(2024, 1, 1)
        date_until = datetime(2024, 1, 31)
        with self.assertRaises(UserError):
            self.provider._obtain_statement_data(date_since, date_until)

    def test_token_reused(self):
        """When a token is set, it is sent instead of user/password."""
        self.provider.wealthreader_token = "existing_token"
        date_since = datetime(2024, 1, 1)
        date_until = datetime(2024, 1, 31)

        with self._mock_request(MOCK_ENTITIES_RESPONSE) as mock_post:
            self.provider._obtain_statement_data(date_since, date_until)
            call_data = mock_post.call_args
            posted_data = call_data[1].get("data") or call_data[0][1]
            self.assertEqual(posted_data["token"], "existing_token")

    def test_operation_date_mode(self):
        """When date_field is operation_date, use that for line dates."""
        self.provider.wealthreader_date_field = "operation_date"
        date_since = datetime(2024, 1, 1)
        date_until = datetime(2024, 1, 31)
        with self._mock_request(MOCK_ENTITIES_RESPONSE):
            lines, _ = self.provider._obtain_statement_data(date_since, date_until)
        # Third transaction has different operation/value dates
        line3 = lines[2]
        self.assertEqual(line3["date"], "2024-01-10")

    def test_value_date_mode(self):
        """When date_field is value_date, use that for line dates."""
        self.provider.wealthreader_date_field = "value_date"
        date_since = datetime(2024, 1, 1)
        date_until = datetime(2024, 1, 31)
        with self._mock_request(MOCK_ENTITIES_RESPONSE):
            lines, _ = self.provider._obtain_statement_data(date_since, date_until)
        # Third transaction: operation_date=01-10, value_date=01-12
        line3 = lines[2]
        self.assertEqual(line3["date"], "2024-01-12")

    def test_test_connection_action(self):
        """Test connection button returns notification action."""
        with self._mock_request(MOCK_ENTITIES_RESPONSE):
            result = self.provider.action_wealthreader_test_connection()
        self.assertEqual(result["type"], "ir.actions.client")
        self.assertEqual(result["tag"], "display_notification")
        self.assertIn("1 account", result["params"]["message"])
