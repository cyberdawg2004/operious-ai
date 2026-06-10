# Anker Pilot Live Support KB: Safety And Recall Escalation

Source basis:
- https://www.anker.com/product-recalls
- https://www.anker.com/a1263-recall
- https://www.anker.com/a1642-a1647-a1652-recall-form
- https://www.anker.com/blogs/power-banks/how-to-ensure-charging-safe-with-power-banks

Use this document whenever a customer mentions a possible battery or charging
safety issue. Safety handling overrides ordinary troubleshooting.

## Safety Signals

Escalate immediately and do not send routine troubleshooting when the message
mentions:

- Smoke, fire, sparks, burning smell, melting plastic, scorch marks, explosion,
  electric shock, or chemical leak.
- Swelling, bulging, puncture, crushed battery, severe drop damage, or water
  damage.
- Device or power bank getting very hot, especially if heat continues after
  unplugging.
- A known or suspected product recall.
- Customer asks whether a recalled unit is safe to keep using.

## Immediate Customer-Safe Guidance

For safety cases, the customer-facing draft should be short and cautious:

- Ask the customer to stop using the product and disconnect it from chargers and
  devices if it is safe to do so.
- Ask them to move it away from flammable materials if safe.
- Do not ask them to reset, recharge, discharge, or continue testing the unit.
- Ask for model number, serial number, order number, purchase date/channel, and
  photos only if safely available.
- Route the case to a human safety or recall queue.

For the governed-send demo, safety cases should normally be denied for automatic
reply and escalated. The important invariant is that the channel must not send a
casual automated troubleshooting response to a safety signal.

## Recall Knowledge

The official Anker product recalls page should be checked for the latest list.
As of this demo pack, Anker lists June 2025 power-bank recalls, including:

- Anker Power Banks with models A1647, A1652, A1681, A1689, and A1257.
- Anker PowerCore 10000 power bank, model A1263.

Anker's A1263 recall page says certain United States units manufactured between
January 1, 2016 and October 30, 2019 and sold between June 1, 2016 and December
31, 2022 may pose a lithium-ion battery fire-safety risk. The customer should
verify model number, order number, and serial number through the official recall
flow.

The A1642/A1647/A1652 recall form covers selected Anker 334 MagGo Battery
(PowerCore 10K), Anker Power Bank, and Anker MagGo Power Bank models purchased
from January 3, 2024 to September 17, 2024. It requests proof of purchase,
serial number, and customer contact details. The customer must not be told they
qualify until the official recall flow confirms eligibility.

## Disposal And Replacement Boundaries

Do not tell customers to throw recalled lithium batteries in household trash or
ordinary recycling. Use a human handoff for disposal instructions because rules
depend on local facilities and recall confirmation.

Do not promise a replacement. Say that the support team will verify recall or
warranty eligibility using model, serial number, order details, and official
Anker guidance.

## Governance

Safety, fire, smoke, swelling, recall, legal threat, and chargeback cases require
human escalation. Automatic response may acknowledge receipt only if the
governance decision explicitly allows that specific safety acknowledgement.
