# Uber Eats order tracking for Home Assistant

![Integration icon](custom_components/uber_eats/brand/icon.png)

[![Validation](https://github.com/bentech/ha-ubereats/actions/workflows/validate.yml/badge.svg)](https://github.com/bentech/ha-ubereats/actions/workflows/validate.yml)
[![MIT License](https://img.shields.io/badge/license-MIT-blue)](LICENSE)

Track your active Uber Eats order in Home Assistant. The integration finds the
order on your signed-in account and exposes its status, ETA, and courier details
when Uber supplies them.

> [!WARNING]
> Uber does not publish or support this endpoint. It can change without notice.
> A copied cookie grants access to your Uber account. Never commit it, paste it
> into an issue, or share it. If a cookie was exposed, sign out of Uber sessions
> and replace it.

## Installation

### HACS or Home Assistant Marketplace

[![Open repository in Home Assistant](https://my.home-assistant.io/badges/hacs_repository.svg)](https://my.home-assistant.io/redirect/hacs_repository/?owner=bentech&repository=ha-ubereats&category=integration)

Use the button or add `bentech/ha-ubereats` as a custom repository in the
**Integration** category. Download **Uber Eats** and restart Home Assistant.
The integration has been tested on Home Assistant 2026.11.

### Manual installation

Copy the entire `custom_components/uber_eats` folder into Home Assistant's
`/config/custom_components/` directory and restart Home Assistant.

## Connect your account

1. Open **Settings → Devices & services → Add integration → Uber Eats**.
2. Open **Orders** on the Uber Eats website in a signed-in desktop browser.
   Open Developer Tools → **Network**, reload the page, and select
   `getActiveOrdersV1`. Under **Request Headers**, copy the value of the
   `Cookie` header and paste it into Home Assistant's masked **Cookie header**
   field.
3. Set the timezone and locale for your account. For the UK, use
   `Europe/London` and `gb`. Submit the form.

The Uber Eats device appears in **Settings → Devices & services**. If the
session expires, use Home Assistant's reauthentication prompt to enter a fresh
cookie.

## Dashboard card

The [example dashboard card](examples/dashboard-card.yaml) shows the restaurant,
order status, timing details, and a **Refresh order** button. The courier map
appears when a position is available. It uses Home Assistant's built-in cards.

On a dashboard you already edit, choose **Edit dashboard → Add card → Manual**,
paste the example YAML, and save. If you renamed the entities, update
`sensor.uber_eats_status`, the timing sensors, and all references to
`button.uber_eats_refresh` and `device_tracker.uber_eats_courier`.

## How it works

1. Home Assistant stores the browser session in the integration's config entry.
2. The client sends a read-only request to Uber Eats' web tracking endpoint
   `getActiveOrdersV1`, using the same account-wide request as the Orders page.
   It sends a null `orderUuid` so new orders can be discovered automatically.
3. The parser uses the web tracking card's status label and extracts the ETA,
   progress, and available courier details. The coordinator tracks one order
   at a time. It picks the first order Uber returns on startup, keeps following
   it while it remains active, and switches to the first remaining order when
   the tracked order leaves the list.
4. The coordinator publishes the result to the entities. It polls every 30
   seconds, and the **Refresh** button requests a poll on demand.

The integration reads tracking information and has no checkout or payment
features.

## Entities and states

| Entity | What it reports |
|---|---|
| `sensor.uber_eats_status` | Current tracking stage and order details |
| `sensor.uber_eats_restaurant` | The restaurant or store name |
| `sensor.uber_eats_earliest_eta` | Earliest arrival timestamp |
| `sensor.uber_eats_latest_eta` | Latest arrival timestamp with the first estimate saved as `original_latest_eta` |
| `sensor.uber_eats_order_placed` | Time the order first appeared in active tracking |
| `sensor.uber_eats_time_in_transit` | Minutes since the ready or pickup stage first appeared |
| `sensor.uber_eats_last_order_outcome` | Most recently observed terminal result, restored across restarts |
| `binary_sensor.uber_eats_order_active` | On while Uber lists the order as active |
| `binary_sensor.uber_eats_courier_arriving` | On when Uber reports the courier is arriving |
| `device_tracker.uber_eats_courier` | Current courier position when available during an active order |
| `button.uber_eats_refresh` | Requests a tracking update |

Before checkout the sensor shows `no_active_order`. Example order stages
include `order_received`, `preparing`, `en_route`, `stop_before_delivery`,
and `arriving`. The intermediate stop stage uses the stop count Uber displays
in its tracking timeline.
The `status_detail` attribute preserves Uber's tracking label so new or
localized labels remain visible.

If an order disappears from Uber's active list during tracking, the sensor
reports `tracking_ended`. Open Uber Eats for the delivery or cancellation
confirmation when the active endpoint omits the outcome. The last-outcome
sensor records `unconfirmed` in this case. Explicit results are `delivered` and
`cancelled`.

The Status sensor also exposes:

- `order_uuid`
- `restaurant`
- `estimated_delivery_time`
- `courier_name`
- `courier_latitude` and `courier_longitude`
- `status_detail`, `progress`, and `progress_segments` when Uber provides them
- `stops_before_delivery` when Uber reports intermediate stops

The ETA sensors convert supported local times and ranges using the configured
order timezone. A single estimate produces the same value in both. Uber's
current ETA text remains available in the Status attributes.

The first latest ETA, first-seen time, and transit timer survive reloads. The
transit timer starts when tracking says the order is ready for pickup. If that
stage is unavailable, it starts when tracking first shows the courier has
collected the order. The timer freezes when tracking ends.

## Troubleshooting

- **Uber rejects the session.** Reauthenticate in Home Assistant with a fresh
  browser cookie.
- **No active order.** Check that the browser session belongs to the account
  that placed the order, then press **Refresh order**.
- **Courier map is hidden.** The map appears when Uber supplies courier
  coordinates. Uber may hide the position during a stop for another order.

For a reproducible problem, include the Home Assistant and integration versions
and the affected tracking stage. Remove session cookies, addresses, and order
identifiers from any logs you share. [Report an issue](https://github.com/bentech/ha-ubereats/issues)

## Development

The custom component lives in `custom_components/uber_eats`. The API client
handles the tracking request and response parsing. The config flow collects
session and regional settings, and the coordinator supplies the sensor and
Refresh button.

Run the parser and HTTP client tests from the repository root with Python 3.12
or later. The tests use synthetic fixtures shaped like tracking responses and
a fake HTTP session.

```bash
python -m pip install pytest ruff
ruff check custom_components tests
python -m pytest -q
```

Use synthetic values for order IDs, names, addresses, and coordinates when
adding test fixtures. Keep account credentials and full network traces out of
commits and bug reports.

## License

This project is distributed under the [MIT License](LICENSE). It is an
unofficial integration for Uber Eats.
