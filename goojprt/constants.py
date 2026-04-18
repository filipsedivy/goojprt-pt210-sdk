"""Hardware constants and platform defaults for the GoojPrt PT-210 driver.

Contents:
    - ``PAPER_WIDTH_PX``: native print head resolution in pixels
      (48 mm of printable width at 203 DPI → 384 pixels).
    - BLE GATT UUIDs: primary set plus alternates used by some firmware
      revisions (vendor-generic ``0000ff0x`` service family).
    - ``SPP_UUID``: the standard Bluetooth Serial Port Profile UUID
      used for RFCOMM connections (Linux only; see ``transport/spp.py``).
    - ``FONT_CANDIDATES``: an ordered list of absolute paths to
      truetype/truetype-collection files used as a platform-independent
      fallback font for bitmap text rendering.
"""

# --- Print head geometry -----------------------------------------------------

#: Print head width in pixels. PT-210 has a 48 mm printable area at 203 DPI,
#: which equals exactly 384 pixels.
PAPER_WIDTH_PX = 384

# --- BLE UUIDs (GoojPrt / Peripage family) -----------------------------------

#: Primary vendor-custom GATT service UUID used by most PT-210 firmware builds.
BLE_SERVICE_UUID = "49535343-fe7d-4ae5-8fa9-9fafd205e455"

#: Primary write characteristic on the vendor-custom service.
BLE_WRITE_CHAR_UUID = "49535343-8841-43f4-a8d4-ecbe34729bb3"

#: Primary notify characteristic used by the printer to report responses
#: (model info, status flags, …).
BLE_NOTIFY_CHAR_UUID = "49535343-1e4d-4bd9-ba61-23c647249616"

#: Alternate service UUID found on some (often older) firmware builds.
#: Uses the generic ``0000ffxx-0000-1000-8000-00805f9b34fb`` pattern.
BLE_SERVICE_UUID_ALT = "0000ff00-0000-1000-8000-00805f9b34fb"

#: Alternate write characteristic accompanying ``BLE_SERVICE_UUID_ALT``.
BLE_WRITE_CHAR_UUID_ALT = "0000ff02-0000-1000-8000-00805f9b34fb"

#: Alternate notify characteristic accompanying ``BLE_SERVICE_UUID_ALT``.
BLE_NOTIFY_CHAR_UUID_ALT = "0000ff01-0000-1000-8000-00805f9b34fb"

# --- Classic Bluetooth (RFCOMM) ---------------------------------------------

#: Standard Serial Port Profile UUID (Bluetooth SIG assigned number).
SPP_UUID = "00001101-0000-1000-8000-00805f9b34fb"

# --- Fallback system fonts ---------------------------------------------------

#: Absolute paths probed in order when the caller does not provide a font.
#: The first existing file is used for bitmap text rendering.
FONT_CANDIDATES = [
    # macOS
    "/System/Library/Fonts/Helvetica.ttc",
    "/Library/Fonts/Arial.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    # Linux
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
    # Windows
    "C:/Windows/Fonts/arial.ttf",
    "C:/Windows/Fonts/calibri.ttf",
]
