# Order-level tax rounding

## Summary

pretix computes and rounds tax for every order line individually. For five €100.00 tickets at 19 %, each line is net 84.03 + tax 15.97. The order totals are then net 420.15, tax 79.85 and gross 500.00. But 19 % of 420.15 is 79.83, so the tax does not "add up" at order level. E-invoicing standards such as EN 16931 require the order-level calculation, so organizers need to choose how taxes are rounded.

Add a per-event choice of tax rounding to the pretix installation in `/app`. Apply it consistently wherever cart and order amounts are calculated.

## Requirements

1. **Rounding modes.** There are three modes:
   - **`line`** is the current behaviour and stays the default: every line is taxed and rounded on its own.
   - **`sum_by_net`**: for each group of lines with the same tax rate and tax code, the group's gross total must equal its net total plus tax, rounded once. Net prices stay unchanged. Gross prices and tax values of some lines move by one minimum currency unit.
   - **`sum_by_net_keep_gross`**: gross prices stay unchanged wherever possible. Tax values (and therefore net prices) of some lines move by one minimum currency unit, so that the group's net total and tax fit its gross total.
2. **Corrections are explicit.** Each correction is stored on the line. The stored `price`/`value` and `tax_value` always *include* the correction, and the correction can be removed again: applying a mode first discards any earlier correction on every line. Lines that end up without a correction carry a correction of `0.00`. A line whose price is zero is never corrected.
3. **Precision.** The minimum unit follows the currency's number of decimal places as pretix already defines them, for example 0.01 EUR or 1 JPY. Totals are rounded half-up to that precision (pretix's existing currency rounding).
4. **Which lines are corrected.** Within a group, lines are considered from the highest gross price to the lowest (the original order breaks ties). Each line takes at most one unit, in that order, until the difference is used up.
5. **Impossible gross prices.** Under `sum_by_net_keep_gross`, some gross totals cannot be reached from any net amount. For example, €23.00 at 7 % is impossible: 21.50 × 1.07 = 23.005 → 23.01, and 21.49 × 1.07 = 22.99. In that case, compute the target net total by rounding gross ÷ (1 + rate), and the achievable gross total from that target net. Adjust gross and tax together (as in `sum_by_net`) until the group reaches the achievable gross total, then apply the remaining tax-only corrections on the following lines.
6. **Event setting and order snapshot.**
   - The mode is an event setting, `tax_rounding` (default `"line"`).
   - Every order stores the mode it was created with in `Order.tax_rounding_mode`.
   - Later changes to that order use the stored mode, not the current event setting.
7. **Where rounding is applied.** Order fees (such as payment fees) are rounded together with the positions. Rounding applies in all of these places:
   - the cart and checkout totals shown to customers;
   - placing an order through the shop;
   - creating an order through the REST API (including `simulate`);
   - changing an order's payment method or payment fee;
   - every change made through the order change manager: adding positions, changing prices, and splitting an order (each resulting order is rounded on its own; a resulting small balance stays pending).

   Rounding changes are recorded in the order's transaction history like any other price change. Payments are always computed on the rounded total. If a gift card does not cover the rounded total, the remainder is paid with the next method as usual.
8. **REST API.**
   - Orders expose `tax_rounding_mode`.
   - Order creation accepts an optional `tax_rounding_mode`.
   - If it is not given, the event setting is used, except for requests from devices whose software brand contains `pretixPOS`. Those get `"line"`, because that app does not know about rounding yet.

## Interface contract

- `pretix.base.services.pricing.apply_rounding(rounding_mode, currency, lines) -> list`.
  - `rounding_mode` is `"line"`, `"sum_by_net"` or `"sum_by_net_keep_gross"`; any other value raises `ValueError`.
  - `lines` is any mix of order positions, cart positions and order fees. They are changed in place.
  - The return value is the list of lines whose values changed, so the caller knows what to save.
- New decimal fields, default `0.00`:
  - `OrderPosition` and `CartPosition`: `price_includes_rounding_correction` and `tax_value_includes_rounding_correction`
  - `OrderFee`: stores the correction of its `value` and `tax_value` in the same way, and exposes them as `price_includes_rounding_correction` and `tax_value_includes_rounding_correction`.
- `OrderFee.price` is an alias of `value`, so fees can be handled exactly like positions.
- New field `Order.tax_rounding_mode`.
- `OrderFee._calculate_tax(tax_rule=None, invoice_address=None, event=None)` accepts an optional `event`.
- The order change manager's internal method `_recalculate_total_and_payment_fee()` is renamed to `_recalculate_rounding_total_and_payment_fee()`. It re-applies the order's rounding mode before recalculating the total and payment fee.
- Worked examples, one group at 19 % with five lines of gross 100.00 / tax 15.97:
  - `sum_by_net` gives gross total 499.98, tax total 79.83 and net total 420.15. The first two lines become 99.99 / 15.96, each with corrections of −0.01.
  - `sum_by_net_keep_gross` gives gross total 500.00, tax total 79.83 and net total 420.17.

## Constraints

- Work only inside `/app`. Do not fetch this project's pull requests, commits or issues from the internet.
- With the default `line` mode, existing orders, carts, invoices and APIs must behave exactly as before.
- Include database migrations for all model changes.
