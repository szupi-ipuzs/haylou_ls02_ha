"""Constants for the Haylou LS02 integration."""

DOMAIN = "haylou_ls02"
MANUFACTURER = "Haylou"
MODEL = "Smart Watch 2"

# BLE Configuration
DEVICE_NAME_FILTER = "Haylou Smart Watch 2"

# BLE Service and Characteristic UUIDs
SERVICE_1_UUID = "000055ff-0000-1000-8000-00805f9b34fb"
SERVICE_2_UUID = "000060ff-0000-1000-8000-00805f9b34fb"

CHAR_GENERAL_RW_1_UUID = "000033f1-0000-1000-8000-00805f9b34fb"
CHAR_DATA2_RW_UUID = "00006001-0000-1000-8000-00805f9b34fb"

CHAR_GENERAL_N_1_UUID = "000033f2-0000-1000-8000-00805f9b34fb"
CHAR_DATA2_N_UUID = "00006002-0000-1000-8000-00805f9b34fb"


# Command IDs (from C++ HaylouWatch.hpp)
CMD_ID_PAIR = 0x20
CMD_ID_UNPAIR = 0x07
CMD_ID_ALREADY_PAIRED = 0x1C
CMD_ID_PAIR_USER_RESPONSE = 0x33
CMD_ID_BATTERY = 0xA2
CMD_ID_FIRMWARE = 0xA1
CMD_ID_TIME = 0x04
CMD_ID_UNITS = 0x01
CMD_ID_USER_ACTION = 0xD1
CMD_ID_HBM_STATUS_REQUEST = 0x18
CMD_ID_HBM_STATUS = 0xE5  # HeartBeatMonitor
CMD_ID_HBM_STATUS2 = 0x16
CMD_ID_HBM_STATISTICS = 0xF7
CMD_ID_SPORT_STATISTICS = 0xB1
CMD_ID_SPORT_STATISTICS2 = 0xB2
SPORT_STATS2_END_MARKER = 0xFD
SPORT_STATS2_RETRY_TIMEOUT_SECONDS = 1
CMD_ID_WEATHER = 0x11
CMD_ID_ALERT_MSG = 0x0F

# Alert Message Types (from C++ Watch::AlertMsgType)
ALERT_MSG_TYPES = {
    "phone_call": 0x00,
    "qq": 0x01,
    "wechat": 0x02,
    "generic": 0x04,
    "facebook": 0x05,
    "twitter": 0x06,
    "whatsapp": 0x07,
    "skype": 0x08,
    "messenger": 0x09,
    "hangouts": 0x0A,
    "line": 0x0B,
    "linkedin": 0x0C,
    "instagram": 0x0D,
    "viber": 0x0E,
    "kakaotalk": 0x0F,
    "vk": 0x10,
    "snapchat": 0x11,
    "googleplus": 0x12,
    "email": 0x13,
    "flickr": 0x14,
    "tumblr": 0x15,
    "pinterest": 0x16,
    "youtube": 0x17,
    "no_icon": 0x18,
}

# Data keys
CONF_DEVICE_ADDRESS = "device_address"
CONF_DEVICE_NAME = "device_name"
CONF_WEATHER_SOURCE = "weather_source"

# Entity types
ENTITY_DEVICE_TRACKER = "device_tracker"
ENTITY_SENSOR = "sensor"

# Coordinator data keys
COORDINATOR_BATTERY = "battery"
COORDINATOR_HMB_STATS = "hmb_stats"
COORDINATOR_CONNECTION_STATE = "connection_state"

# Service names
SERVICE_SEND_MESSAGE = "send_message"

# Device tracker presence
TRACKER_STATE_HOME = "Home"
TRACKER_STATE_AWAY = "Away"
BLE_PRESENCE_TIMEOUT_MINUTES = 10

# Notification payload filters
FILTER_BATTERY_RESULT = b"\xa2"
FILTER_HBM_STATISTICS_RESULT = bytes([CMD_ID_HBM_STATISTICS, 0x04])
FILTER_HBM_STATISTICS2_RESULT = bytes([CMD_ID_HBM_STATISTICS, 0x03])
