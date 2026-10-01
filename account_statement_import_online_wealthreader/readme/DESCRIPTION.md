Online bank statements from Wealth Reader AIS.

The self-hoster supplies a `WEALTHREADER_API_KEY`, registers
`https://<odoo>/wealthreader/response` as an OAuth redirect with
`access_type=oauth` and `tokenize=1`, then connects a journal IBAN to a
Wealth Reader entity. The OAuth callback accepts `code` plus `state` or
`nonce` because Wealth Reader may omit `state`.
