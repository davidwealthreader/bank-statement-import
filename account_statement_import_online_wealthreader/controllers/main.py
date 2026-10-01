# Copyright 2026 Wealth Reader
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).

import werkzeug
from werkzeug.urls import url_encode

from odoo import http
from odoo.http import request


class WealthReaderController(http.Controller):
    @http.route("/wealthreader/response", type="http", auth="public", csrf=False)
    def wealthreader_response(self, **post):
        Provider = request.env["online.bank.statement.provider"].sudo()
        current_provider = Provider.browse()
        state = post.get("state")
        nonce = post.get("nonce")
        if state:
            domain = [("wealthreader_pkce_state", "=", state)]
            if str(state).isdigit():
                domain = ["|", ("id", "=", int(state))] + domain
            current_provider = Provider.search(domain, limit=1)
        if not current_provider and nonce:
            current_provider = Provider.search(
                [("wealthreader_pkce_nonce", "=", nonce)],
                limit=1,
            )

        params = {
            "action": request.env.ref(
                "account_statement_import_online.online_bank_statement_provider_action"
            ).id,
            "model": "online.bank.statement.provider",
        }
        if current_provider and post.get("code"):
            current_provider._wealthreader_complete_authorization(post["code"])
            params.update({"view_type": "form", "id": current_provider.id})
        else:
            params["view_type"] = "list"
        return werkzeug.utils.redirect("/web#" + url_encode(params), 303)
