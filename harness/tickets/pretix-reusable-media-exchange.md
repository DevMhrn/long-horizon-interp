# Exchange a ticket for a reusable medium at check-in

## Summary

Festivals using pretix want to turn a printed ticket into a wristband or chip card at the entrance. When the ticket is scanned, staff hand out a reusable medium, and it becomes linked to that ticket from then on. Today, reusable media can only be connected through order creation or the admin interface, and the check-in API has no way to perform an exchange.

Build medium exchange into the check-in flow of the pretix installation in `/app` (API endpoint `POST /api/v1/organizers/{organizer}/checkinrpc/redeem/`), and make the product media policies expressive enough to control it.

## Requirements

1. **Two new product media policies.** On products (`Item`), `"append"` requires an existing medium, and `"append_or_new"` accepts either an existing or a new medium. Both *add* the ticket to the medium's existing linked tickets. The existing `"reuse"` and `"reuse_or_new"` policies keep *replacing* the medium's previous tickets, and `"new"` requires a medium that does not exist yet.
2. **This applies everywhere a ticket is connected to a medium.** When an order is created through the API with `use_reusable_medium`, an append policy adds the new ticket to the medium, and a reuse policy replaces the medium's tickets with the new one.
3. **Exchange on redeem.** The redeem request accepts two optional fields, `exchange_medium_type` and `exchange_medium_identifier`. When both are given and the scanned ticket passes all normal checks, the ticket is linked to that medium according to the product's policy and the check-in succeeds (HTTP 201, `status "ok"`). If the product's policy allows creating a new medium and the organizer has gift-card auto-creation enabled for that media type, a newly created medium gets its gift card exactly as it would when created elsewhere.
4. **Exchange required.** If the product's policy is `"new"`, the scanned ticket is not linked to any medium yet, no exchange is requested and `force` is not set, the check-in is refused with HTTP 400. The response has `status "exchange"` plus `media_policy` and `media_type` taken from the product, so a scanning app knows what to hand out. A ticket that is already linked to a medium, or a forced check-in, succeeds normally.
5. **Enforcing media usage.** Add an organizer setting `reusable_media_usage_enforced` (boolean, default off). When it is on, scanning the original ticket barcode of a ticket that is already linked to a reusable medium fails with reason `already_exchanged`, unless `force` is set. Scanning the medium itself keeps working. Requesting an exchange for a ticket that is already linked to a medium always fails with `already_exchanged`, whatever the setting.
6. **Expired media are invalid.** A medium whose `expires` lies in the past must be treated as expired and cannot be used for an exchange.

## Interface contract

- New constants on `Item`: `MEDIA_POLICY_APPEND = "append"` and `MEDIA_POLICY_APPEND_OR_NEW = "append_or_new"`.
- New check-in failure reasons, stored and reported like the existing ones: `already_exchanged`, `medium_invalid` and `medium_exists`.
- Validation errors are HTTP 400 in the serializer error format:
  - Only one of the two exchange fields is set: `{"non_field_errors": ["If you set any of exchange_medium_type or exchange_medium_identifier, you need to set both of them."]}`
  - `exchange_medium_type` is not a known media type: the standard invalid-choice error on that field, e.g. `"\"unknown\" is not a valid choice."`
- Exchange failures are HTTP 400 with `status "error"`. The checks are applied in the order below, and the first one that fails determines the response:

  | # | Situation | `reason` | `reason_explanation` |
  |---|---|---|---|
  | 1 | The scanned code is itself a reusable medium | `error` | (any) |
  | 2 | The media type is not enabled for the organizer | `error` | `Medium type is not enabled for organizer.` |
  | 3 | The product's `media_type` differs from `exchange_medium_type` | `product` | `Incorrect medium type for product.` |
  | 4 | The ticket is already linked to a reusable medium | `already_exchanged` | (any) |
  | 5 | Existing-medium policy, but the medium does not exist or is expired | `medium_invalid` | (any) |
  | 5 | New-medium policy, but the identifier is rejected by the media type's own identifier rules, or the media type cannot register previously unknown identifiers at scan time (of the built-in types, only `nfc_uid` can) | `medium_invalid` | (any) |
  | 5 | Policy `"new"`, but the medium already exists | `medium_exists` | (any) |
  | 6 | The product has no media policy | `product` | `Product does not support medium exchange.` |

## Constraints

- Work only inside `/app`. Do not fetch this project's pull requests, commits or issues from the internet.
- Existing check-in, order and reusable-media behavior must keep working.
- Include a database migration for any model change.
