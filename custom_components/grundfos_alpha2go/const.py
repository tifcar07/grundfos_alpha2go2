"""Constants for the Grundfos Alpha2 Go integration."""

DOMAIN = "grundfos_alpha2go"

CONF_ADDRESS = "address"
CONF_NAME = "name"

DEFAULT_NAME = "Alpha2 Go"
DEVICE_NAME_PREFIX = "Alpha"
GRUNDFOS_MANUFACTURER_ID = 1183

# Intervalle de lecture GENIbus (connexion courte, puis déconnexion).
# 120 s suffit largement pour savoir si un circulateur tourne.
DEFAULT_SCAN_INTERVAL = 120

# Seuils "pompe en marche"
RUNNING_POWER_THRESHOLD_W = 3.0
RUNNING_SPEED_THRESHOLD_RPM = 100.0

# Anciennes clés d'entités (v1.x) supprimées automatiquement au démarrage
LEGACY_SENSOR_KEYS = ("connected", "device_name", "model", "firmware", "notifications")
