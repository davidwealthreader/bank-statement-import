# Copyright 2026 Wealth Reader
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
import hashlib
import json
import secrets
import string
from urllib.parse import urlencode

import requests
from werkzeug.urls import url_join

from odoo import _, api, fields, models
from odoo.exceptions import UserError

API_BASE = "https://api.wealthreader.com"
OAUTH_BASE = "https://oauth.wealthreader.com"
AUTH_ERROR_CODES = {1010, 1020, 2010, 2020}
REQUESTS_TIMEOUT = 120
ALPHABET = string.ascii_letters + string.digits


def _random_alnum(length=41):
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def _hex_alnum(length=41):
    return _random_alnum(length).encode("ascii").hex()


class OnlineBankStatementProvider(models.Model):
    _inherit = "online.bank.statement.provider"

    wealthreader_entity_code = fields.Char()
    wealthreader_token = fields.Char(readonly=True)
    wealthreader_account_uuid = fields.Char(readonly=True)
    wealthreader_pkce_nonce = fields.Char(readonly=True)
    wealthreader_pkce_state = fields.Char(readonly=True)
    wealthreader_pkce_verifier = fields.Char(readonly=True)
    wealthreader_country_code = fields.Char(default="ES")

    @api.model
    def _get_available_services(self):
        return super()._get_available_services() + [
            ("wealthreader", "Wealth Reader"),
        ]

    def _wealthreader_callback_url(self):
        base_url = self.env["ir.config_parameter"].sudo().get_param("web.base.url")
        return url_join(base_url, "wealthreader/response")

    def _wealthreader_interpret(self, response, path):
        if response.status_code == 429:
            raise UserError(_("Wealth Reader rate limited on %s") % path)
        if response.status_code in (401, 410):
            raise UserError(_("Wealth Reader session expired. Reconnect the bank."))
        if response.status_code not in (200, 201):
            raise UserError(
                _("Wealth Reader %(path)s failed with HTTP %(code)s")
                % {"path": path, "code": response.status_code}
            )
        data = response.json()
        if data.get("success") is False:
            error = data.get("error") or {}
            code = int(error.get("code") or 0)
            message = error.get("message") or "success=false"
            if code in AUTH_ERROR_CODES:
                raise UserError(
                    _("Wealth Reader requires a new bank login (%s): %s")
                    % (code, message)
                )
            raise UserError(_("Wealth Reader error %s: %s") % (code, message))
        return data

    def action_wealthreader_connect(self):
        self.ensure_one()
        if not self.username:
            raise UserError(_("Set the Wealth Reader API key first."))
        if not self.wealthreader_entity_code:
            raise UserError(_("Set the Wealth Reader entity code first."))
        if not self.journal_id.bank_account_id:
            raise UserError(
                _("Configure a bank account on journal %s")
                % self.journal_id.display_name
            )

        nonce = _hex_alnum()
        state = str(self.id)
        verifier = _hex_alnum()
        challenge = hashlib.sha256(verifier.encode("ascii")).hexdigest()
        wr_conf = json.dumps(
            {
                "operation_id": f"op_{secrets.token_hex(8)}",
                "entities_to_display": [self.wealthreader_entity_code],
                "wait_full_response": True,
            }
        ).encode("utf-8").hex()
        redirect_uri = self._wealthreader_callback_url()
        self.write(
            {
                "wealthreader_pkce_nonce": nonce,
                "wealthreader_pkce_state": state,
                "wealthreader_pkce_verifier": verifier,
            }
        )
        query = urlencode(
            {
                "challenge_code": challenge,
                "code_challenge_method": "S256",
                "redirect_uri": redirect_uri,
                "response_type": "code",
                "state": state,
                "nonce": nonce,
                "wr_conf": wr_conf,
            }
        )
        return {
            "type": "ir.actions.act_url",
            "url": f"{OAUTH_BASE}/oauth2/?{query}",
            "target": "self",
        }

    def _wealthreader_complete_authorization(self, code):
        self.ensure_one()
        if not self.wealthreader_pkce_verifier:
            raise UserError(_("PKCE verifier missing. Restart the bank link."))
        response = requests.post(
            f"{OAUTH_BASE}/token/",
            data={
                "grant_type": "authorization_code",
                "redirect_uri": self._wealthreader_callback_url(),
                "code": code,
                "code_verifier": self.wealthreader_pkce_verifier,
            },
            headers={"Accept": "application/json"},
            timeout=REQUESTS_TIMEOUT,
        )
        data = self._wealthreader_interpret(response, "POST /token/")
        statistics = data.get("statistics") or {}
        token = statistics.get("token")
        entity_code = statistics.get("code") or self.wealthreader_entity_code
        if not token:
            raise UserError(_("Wealth Reader did not return a token."))
        self.write(
            {
                "wealthreader_token": token,
                "wealthreader_entity_code": entity_code,
                "wealthreader_pkce_nonce": False,
                "wealthreader_pkce_state": False,
                "wealthreader_pkce_verifier": False,
            }
        )
        self._wealthreader_match_journal_account(data)
        return True

    def _wealthreader_refresh(self, date_from=None):
        self.ensure_one()
        if not self.username or not self.wealthreader_token:
            raise UserError(_("Wealth Reader is not connected."))
        body = {
            "api_key": self.username,
            "code": self.wealthreader_entity_code,
            "token": self.wealthreader_token,
            "product_types": "accounts",
        }
        if date_from:
            body["date_from"] = fields.Date.to_string(date_from)
        response = requests.post(
            f"{API_BASE}/entities/",
            data=body,
            headers={"Accept": "application/json"},
            timeout=REQUESTS_TIMEOUT,
        )
        return self._wealthreader_interpret(response, "POST /entities/")

    def _wealthreader_accounts(self, data):
        payload = data.get("payload") or {}
        return payload.get("accounts") or data.get("accounts") or []

    def _wealthreader_match_journal_account(self, data):
        own_iban = (self.journal_id.bank_account_id.sanitized_acc_number or "").upper()
        found = False
        ibans = []
        for account in self._wealthreader_accounts(data):
            iban = (account.get("code") or "").upper()
            uid = account.get("uuid") or account.get("code")
            if iban:
                ibans.append(iban)
            if uid and iban == own_iban:
                self.wealthreader_account_uuid = uid
                found = True
                break
        if found:
            self.sudo().message_post(
                body=_(
                    "Your account number %(iban_number)s is successfully attached."
                )
                % {"iban_number": self.journal_id.bank_account_id.display_name}
            )
            return True
        self.sudo().message_post(
            body=_(
                "Your account number %(iban_number)s is not in the IBAN "
                "account numbers found %(accounts_iban)s, please check"
            )
            % {
                "iban_number": self.journal_id.bank_account_id.display_name,
                "accounts_iban": " / ".join(ibans) or "-",
            }
        )
        return False

    def _obtain_statement_data(self, date_since, date_until):
        self.ensure_one()
        if self.service == "wealthreader":
            return self._wealthreader_obtain_statement_data(date_since, date_until)
        return super()._obtain_statement_data(date_since, date_until)

    def _wealthreader_obtain_statement_data(self, date_since, date_until):
        self.ensure_one()
        if not self.wealthreader_account_uuid:
            return
        try:
            data = self._wealthreader_refresh(date_from=date_since)
        except UserError as err:
            self.sudo().message_post(body=str(err))
            return [], {}

        account = next(
            (
                row
                for row in self._wealthreader_accounts(data)
                if row.get("uuid") == self.wealthreader_account_uuid
                or row.get("code") == self.wealthreader_account_uuid
            ),
            None,
        )
        if not account:
            return [], {}

        res = []
        sequence = 0
        until = fields.Date.to_date(date_until) if date_until else None
        for transaction in account.get("transactions") or []:
            amount = transaction.get("amount")
            try:
                amount = float(amount)
            except (TypeError, ValueError):
                continue
            string_date = (
                transaction.get("date")
                or transaction.get("booking_date")
                or transaction.get("value_date")
            )
            if not string_date:
                continue
            current_date = fields.Date.from_string(str(string_date)[:10])
            if until and current_date > until:
                continue
            sequence += 1
            name = (
                transaction.get("name")
                or transaction.get("description")
                or transaction.get("counterpart")
                or "/"
            )
            unique_id = (
                transaction.get("uuid")
                or transaction.get("id")
                or f"{self.wealthreader_account_uuid}-{string_date}-{amount}-{name}"
            )
            res.append(
                {
                    "sequence": sequence,
                    "date": current_date,
                    "ref": name,
                    "payment_ref": transaction.get("description") or name,
                    "unique_import_id": unique_id,
                    "amount": amount,
                    "account_number": False,
                    "partner_name": transaction.get("counterpart")
                    or transaction.get("counterparty"),
                    "narration": transaction.get("description") or name,
                }
            )
        return res, {}
