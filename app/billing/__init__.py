"""Billing: Monobank payments, renewals, saved cards, auto-renewal.

- monobank.py: the only code that talks to Monobank over HTTP
- service.py: payment state transitions and the billing worker cycle
- routes.py: /api endpoints for invoices, payments, cards, renewals
"""
