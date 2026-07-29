"""Constants for the Sunshare integration."""
from __future__ import annotations

from datetime import timedelta

DOMAIN = "sunshare"

# Only host confirmed to work live (see API_DOCUMENTATION.md §1).
BASE_URL = "https://web.sunsharetek.com/app/"

CONF_USER_ACCOUNT = "user_account"

DEFAULT_SCAN_INTERVAL = 30
MIN_SCAN_INTERVAL = 10
SCAN_INTERVAL_STEP = 5

# Coordinator falls back to this if no options are set yet.
DEFAULT_UPDATE_INTERVAL = timedelta(seconds=DEFAULT_SCAN_INTERVAL)

# API paths. These already include the doubled "app/" prefix required by the
# real endpoint strings (BASE_URL itself ends in "/app/") — see
# API_DOCUMENTATION.md §1 "Path-prefix gotcha".
PATH_LOGIN = "auth/login"
PATH_DEVICE_LIST = "app/sysDeviceInfo/findDeviceListByUserId"
PATH_DEVICE_DETAIL = "app/sysDeviceInfo/findById"
PATH_MES_SETTING = "app/sysDeviceInfo/queryMesSettingUpdate"
PATH_UPDATE_EMS_PARA = "app/sysDeviceInfo/updateEmsParaById"
PATH_SUMMARY = "app/inveRealDataMinute/selectInveSummary"
PATH_BATTERY_STATUS = "app/sysDeviceInfo/findBatteryAndDsSsById"

MANUFACTURER = "Sunshare"
