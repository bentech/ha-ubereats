"""Constants for the Uber Eats integration."""

from datetime import timedelta

DOMAIN = "uber_eats"
ACTIVE_ORDERS_ID = "active_orders"
CONF_COOKIE = "cookie"
CONF_LOCALE = "locale"
CONF_ORDER_UUID = "order_uuid"
CONF_TIMEZONE = "timezone"

DEFAULT_LOCALE = "gb"
DEFAULT_TIMEZONE = "Europe/London"
UPDATE_INTERVAL = timedelta(seconds=30)
