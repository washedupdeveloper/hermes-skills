# IoT node hardware, power and kit distribution

Notes for choosing parts and packaging an ESP32-class sensor node, including when
the build is handed to other people as a kit. Prices, stock and specs move —
re-check the vendor page before publishing a BoM.

## Node architecture

- One node per sensing location. Keep the sensor cable short (under ~30 cm):
  analog signals over long cable pick up noise and I2C over long cable is worse.
  Do not centralise one node per room and run probes back to it.
- Prefer a board that already integrates the power path — onboard Li-ion
  charging, a battery connector, solar input — over bolting on a charging module.
  Each extra module is a failure mode and a support conversation.
- The board's own deep-sleep figure sets the battery ceiling, not the SoC
  datasheet: the regulator, USB bridge, flash and any onboard divider dominate.
- Check for onboard parts you cannot switch off. An always-on power LED or a
  permanent battery-divider drain is a large fraction of a deep-sleep budget.

## Sensor selection

- Soil moisture: capacitive only. Resistive probes pass DC through the soil,
  electrolyse and corrode visibly within weeks — the single most common wrong
  purchase. A vendor capacitive probe with an onboard regulator works at 3.3 V;
  a waterproof/IP65 variant is worth the extra cost outdoors or permanently wet.
- Air temperature and humidity: a modern digital I2C sensor (SHT3x/SHT4x class).
  Do not use the cheap hobby DHT parts — poor accuracy, slow, and they drift.
- Light: a digital lux sensor over I2C is cheap and sufficient for "is this
  getting light". It needs a clear window in the enclosure, which makes it the
  most skippable metric if the enclosure is sealed.
- Soil temperature: a waterproof probe is a genuinely different measurement from
  air temperature, and survives in soil indefinitely.
- Buy all units of a cheap sensor from one seller in one order, or pay for the
  branded part. Consistency across unbranded clone boards is poor, and every
  unit needs its own calibration regardless.

## Do not buy

- Resistive soil probes (fork-shaped, two bare metal prongs) — corrosion.
- DHT11 / DHT22 — accuracy and drift.
- Gas sensors with internal heaters (MQ-x class) — tens of mA continuously.
- Cheap pH / EC / NPK soil probes — unreliable and they drift within weeks. The
  industrial RS485 versions work but need a separate supply and cost an order of
  magnitude more.
- 5 V-only sensor breakouts on a 3.3 V node without level shifting.
- Anything with an always-on indicator LED you cannot disable.
- Generic capacitive clone boards unless the kit includes a per-unit calibration
  step.

## Power: gating and sampling

- Power-gate every sensor from a GPIO: raise the pin, let it settle (order
  100 ms), read, then drop it. A continuously powered capacitive soil sensor
  draws a few mA, which alone turns a year into weeks. A GPIO can source enough
  current for a sensor of this class, so no switch is needed.
- Sample on the interval the physics requires, not the shortest one available.
  Soil moisture and air conditions move over hours and days; a node waking every
  minute buys nothing and costs everything.
- Battery-life arithmetic: average current = deep-sleep current + (wake cost /
  wake interval), where wake cost is the seconds spent associating and publishing
  times the average current in that window. The radio wake dominates; gated
  sensors are negligible. Work the number for each candidate interval, state the
  assumptions, and never quote a runtime you have not measured on the real board.

## Analog reading

- The ESP32's built-in ADC is nonlinear and noisy — advertised bits behave like
  fewer bits with a dead zone at the bottom. For a relative dry/ok/wet score,
  read raw, average several samples, and apply a per-unit calibration.
- When a real physical percentage is needed, add an external 16-bit I2C ADC next
  to the probe. It is inexpensive and removes a class of "my numbers look wrong"
  support messages.

## Calibration

- Every capacitive probe needs per-unit calibration: record the raw reading in
  air (dry) and in water (wet), then map between them.
- Store calibration on the server keyed by device, not in firmware. Hardcoded
  values mean a sensor replacement needs a reflash; keyed by device it is a
  configuration change.
- Make calibration part of onboarding. Without it the readings are meaningless
  and the user cannot tell.

## Enclosure

- Vent the temperature/humidity sensor to room air — sealed in a box it measures
  the box.
- Give the light sensor a clear window.
- Use a gland or grommet for the probe cable; keep the electronics sealed.
- Leave the programming port reachable for the first flash, or provide a pad
  header.

## Distributing the build as a kit

- Minimise the firmware you must support remotely. Every custom line is debugged
  at someone else's house, on their network, with them holding the device.
- Prefer a declarative firmware stack that already provides browser-based
  provisioning over BLE/serial, OTA updates, and browser-based flashing.
  Solving those three yourself costs weeks per user and buys nothing.
- Flash and test nodes before shipping, or ship a pre-built binary plus
  browser-flashing instructions. Recipients should never install a toolchain.
- Ship OTA and a firmware version reported in telemetry before the first node
  leaves. Without both, one bug is one physical visit per device.
- Deploy the server as a one-command container stack the recipient runs
  themselves. Hosting their data makes you their administrator permanently,
  which is a worse job than being their firmware author.
- Prefer a mesh VPN for remote access over hand-rolled tunnels — the recipient
  signs in with an identity they already have. Keep broker ACLs even on a
  trusted LAN.
- Self-reporting by the user is a first-class data source, not a fallback: an
  "I did it" action carries most of the behavioural signal for free, and a sensor
  that disagrees with a user's report (soil still dry after a claimed watering)
  is a more interesting signal than either channel alone.
- Sensors earn their cost as ground truth for whether the advice was right, and
  as detection of the neglect the user does not self-report. They are not the
  main behavioural signal, and the marginal value of the Nth sensor is low.

## Sources

- ESP32-C6 datasheet (current consumption, sleep modes):
  https://documentation.espressif.com/esp32-c6_datasheet_en.html
- ESP-IDF current-consumption measurement guide:
  https://docs.espressif.com/projects/esp-idf/en/stable/esp32c6/api-guides/current-consumption-measurement-modules.html
- Vendor board and sensor wiki pages (sleep current, pinout, calibration example
  code): the DFRobot wiki for the FireBeetle 2 ESP32-C6 and the capacitive soil
  moisture probe SKUs, and the Seeed wiki for the XIAO ESP32C6
- Sensirion SHT4x / SHT3x and BH1750 datasheets (sensor accuracy and I2C address)
- Home Assistant MQTT discovery: https://www.home-assistant.io/integrations/mqtt
- openHAB Home Assistant MQTT Components binding:
  https://www.openhab.org/addons/bindings/homeassistant
- ESPHome sensor components (adc attenuation, sht4x, bh1750) at
  https://esphome.io/components/
- Open provisioning standard and browser-based flashing tool docs:
  https://improv-wifi.com/ , https://esphome.github.io/esp-web-tools
