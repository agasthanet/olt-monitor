"""
Compatibility shim — logic SNMP ada di folder parsers/.

  from snmp_zte import OnuInfo, fetch_all_onts, ...
masih didukung.
"""
from parsers import *  # noqa: F401,F403
from parsers.common import *  # noqa: F401,F403
from parsers.router import fetch_all_onts  # noqa: F401
from parsers.zte import detect_firmware  # noqa: F401
