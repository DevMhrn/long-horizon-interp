# Tax compliance for fees, cancellations and order totals

## Summary

Organizers using pretix for e-invoicing keep running into the same three tax problems:

1. The "default tax rate" is a loose event setting that is used for far more than it says, and fees can't be taxed the way the law requires. Cancellation fees in particular often have to be split across the tax rates of the cancelled tickets.
2. Cancelling a whole event can refund a large amount of money instantly, with no preview.
3. Taxes are rounded per line, so order totals don't match the order-level calculation that e-invoicing standards such as EN 16931 require.

Solve all three in the pretix installation in `/app`.

## Part A: default tax rule and fee taxation

1. **Default tax rule.**
   - Each event has at most one default tax rule, stored as a boolean `default` on `TaxRule`. Making one rule the default clears the flag on the others.
   - The first tax rule created for an event (through the REST API or the backend) becomes the default automatically, unless `default` is given explicitly.
   - The REST API tax-rule resource exposes and accepts `default`.
   - `Event.cached_default_tax_rule` returns the event's default rule, or `None`.
   - The backend has a POST endpoint `…/settings/tax/<rule id>/default` that makes that rule the default. It needs the "can change event settings" permission.
   - The default rule cannot be deleted while the event has other tax rules.
   - When an event is copied or cloned, the copy of the source's default rule becomes the new event's default.
2. **Payment fee taxation.** New event setting `tax_rule_payment`:
   - `"default"` (the default value) taxes payment fees with the default tax rule;
   - `"none"` charges no tax on them.
3. **Cancellation fee taxation.** New event setting `tax_rule_cancellation`:
   - `"none"` (the default value): the cancellation fee is untaxed and has no tax rule.
   - `"default"`: the fee is taxed with the default tax rule.
   - `"split"`: the fee is split into one cancellation fee per tax rule of the order, using the split rule below.
4. **Splitting a fee across tax rules.** Add `pretix.base.services.tax.split_fee_for_taxes(lines, fee_gross, event)`.
   - It takes the order's positions and fees, and returns `[(tax_rule, gross_amount), …]`, sorted by tax rate ascending.
   - The amounts are proportional to each rule's share of the lines' **gross** total. They add up exactly to `fee_gross`.
   - Any rounding remainder benefits the highest tax rate.
   - Example: lines of 11.90 at 19 % and 10.70 at 7 % with a fee of 0.03 give `[(7 %, 0.01), (19 %, 0.02)]`.

## Part B: safe event cancellation

5. **Dry run.** The event cancellation task `cancel_event(...)` accepts `dry_run=False`.
   - With `dry_run=True` it changes nothing: no order is cancelled, refunded or changed, and no email is sent.
   - It returns a dict whose `refund_total` is the exact total a real run with the same arguments would owe back to customers: the paid amounts that become refundable, minus any fees that are kept. This is independent of whether refunds would be executed automatically, manually or not at all.
   - Without `dry_run`, cancellation behaves as before.

## Part C: order-level tax rounding

6. **Rounding modes.** There are three modes:
   - **`line`** is the current behaviour and stays the default: every line is taxed and rounded on its own.
   - **`sum_by_net`**: for each group of lines with the same tax rate and tax code, the group's gross total must equal its net total plus tax, rounded once. Net prices stay unchanged. Gross prices and tax values of some lines move by one minimum currency unit.
   - **`sum_by_net_keep_gross`**: gross prices stay unchanged wherever possible. Tax values (and therefore net prices) of some lines move by one minimum currency unit, so that the group's net total and tax fit its gross total.
7. **Corrections are explicit.** Each correction is stored on the line. The stored `price`/`value` and `tax_value` always *include* the correction.
   - Applying a mode first discards any earlier correction on every line.
   - Lines without a correction carry `0.00`.
   - A line whose price is zero is never corrected.
8. **Precision.** The minimum unit follows the currency's decimal places as pretix already defines them (0.01 EUR, 1 JPY). Totals are rounded half-up to that precision.
9. **Which lines are corrected.** Within a group, lines are considered from the highest gross price to the lowest (the original order breaks ties). Each line takes at most one unit, in that order, until the difference is used up.
10. **Impossible gross prices.** Under `sum_by_net_keep_gross`, some gross totals cannot be reached from any net amount (e.g. €23.00 at 7 %).
    - Compute the target net total as gross ÷ (1 + rate), rounded.
    - Compute the achievable gross total from that target net.
    - Adjust gross and tax together (as in `sum_by_net`) until the group reaches the achievable gross total.
    - Then apply the remaining tax-only corrections on the following lines.
11. **Event setting and order snapshot.** The mode is an event setting, `tax_rounding` (default `"line"`). Every order stores its mode in `Order.tax_rounding_mode`, and later changes to that order use the stored mode.
12. **Where rounding is applied.** Order fees are rounded together with the positions, in all of these places:
    - the cart and checkout totals shown to customers. Before a payment method is chosen, no payment fee is part of the rounded amounts.
    - placing an order through the shop;
    - REST API order creation (including `simulate`);
    - changing an order's payment method or fee;
    - every change made through the order change manager (adding positions, changing prices, splitting). Each resulting order is rounded on its own, and a resulting small balance stays pending.

    Rounding changes are recorded in the order's transaction history like any other price change. Payments use the rounded total; if a gift card does not cover it, the remainder is paid with the next method.
13. **REST API.**
    - Orders expose `tax_rounding_mode`, and order creation accepts it. This is the only new field in the order API. The correction fields are not exposed there.
    - If it is not given, the event setting is used, except for devices whose software brand contains `pretixPOS`. Those get `"line"`.

## Interface contract (rounding)

- `pretix.base.services.pricing.apply_rounding(rounding_mode, currency, lines) -> list`.
  - It mutates `lines` (any mix of order positions, cart positions and order fees) and returns the lines whose values changed.
  - An unknown mode raises `ValueError`.
- New decimal fields, default `0.00`:
  - `OrderPosition` and `CartPosition`: `price_includes_rounding_correction` and `tax_value_includes_rounding_correction`.
  - `OrderFee` stores the corrections of its `value` and `tax_value` and exposes them under the same two names. `OrderFee.price` is an alias of `value`.
- New field `Order.tax_rounding_mode`.
- `OrderFee._calculate_tax(tax_rule=None, invoice_address=None, event=None)` accepts an optional `event`.
- The order change manager's internal `_recalculate_total_and_payment_fee()` is renamed to `_recalculate_rounding_total_and_payment_fee()` and re-applies the order's rounding mode.
- Worked example, one group at 19 % with five lines of gross 100.00 / tax 15.97 (net 84.03 each):
  - `sum_by_net` gives 499.98 gross, 79.83 tax and 420.15 net. The first two lines become 99.99 / 15.96, with corrections of −0.01.
  - `sum_by_net_keep_gross` gives 500.00 gross, 79.83 tax and 420.17 net.

## Constraints

- Work only inside `/app`. Do not fetch this project's pull requests, commits or issues from the internet.
- With the default settings, existing orders, carts, invoices, cancellations and APIs must behave exactly as before.
- Include database migrations for all model changes.
