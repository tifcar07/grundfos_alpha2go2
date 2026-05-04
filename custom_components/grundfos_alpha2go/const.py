"""Constants for the Grundfos Alpha2 Go integration."""

DOMAIN = "grundfos_alpha2go"

# Config entry keys
CONF_ADDRESS = "address"
CONF_NAME    = "name"

# Default values
DEFAULT_NAME          = "Alpha2 Go"
DEFAULT_SCAN_INTERVAL = 30   # seconds

# BLE device prefix (Grundfos pumps advertise with this name prefix)
DEVICE_NAME_PREFIX = "Alpha"

# Attributes
ATTR_FLOW    = "flow"
ATTR_HEAD    = "head"
ATTR_SPEED   = "speed"
ATTR_POWER   = "power"
ATTR_VOLTAGE = "voltage"
ATTR_CURRENT = "current"
