from __future__ import annotations

from logand_backend.app.config import AppConfig


def is_configured(cfg: AppConfig) -> bool:
    """True once BOTH halves of a real Stripe key pair are set -- mirrors
    paypal.is_configured's convention (domain/payments/providers/paypal.py).

    Checking the publishable key alone (FINDINGS.md M1) is not enough: the
    browser needs stripe_publishable_key to mount Payment Element, but the
    server needs payment_processor_secret to actually mint/confirm a
    PaymentIntent. Advertising "stripe": true off the publishable key alone
    let an operator set a real pk_ while payment_processor_secret was still
    unset (or a mismatched test/live pair) -- the button would show, but
    every /pay call would 401 against Stripe, stranding the customer at a
    card form that can never complete. Requiring both here closes that gap;
    every caller (GET /payment-methods, POST /pay) checks this BEFORE ever
    calling into stripe-python, same "hide/refuse what can't work" pattern
    as PayPal.
    """
    return bool(cfg.payment_processor_secret and cfg.stripe_publishable_key)
