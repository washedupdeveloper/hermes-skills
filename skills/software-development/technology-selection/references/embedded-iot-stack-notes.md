# Embedded IoT stack notes: ESP32, Zigbee / Thread / Matter, MQTT

Condensed domain notes for embedded platform selection. Verify against current
primary sources before quoting any cell — this is a starting map, not a
substitute for the vendor page.

## Chip capability (ESP32 family)

- 802.15.4 radio (Zigbee / Thread / Matter-over-Thread): ESP32-H2 (BLE +
  802.15.4, no Wi-Fi), ESP32-C6 (Wi-Fi 6 + BLE + 802.15.4), ESP32-C5,
  ESP32-C61. Classic ESP32, S3 and C3 have no 802.15.4 radio at all.
- On C5/C6 the 802.15.4 radio cannot run concurrently with Wi-Fi. For a pure
  Thread or Zigbee node prefer H2 — coexistence problems on C6 are a reported
  cause of flakiness.
- MQTT needs IP, so ESP32-H2 (no Wi-Fi) is out for a Wi-Fi MQTT node. Use C3
  (cheapest) or C6 (keeps 802.15.4 as a future option).
- Board-level sleep is dominated by the LDO, USB bridge and flash, not the SoC.
  ESP32-C6 chip figures: deep sleep ~7 µA, light sleep ~180 µA, modem sleep
  ~17 mA; measured on a small dev board, deep sleep lands around 15 µA.
- Dedicated mesh SoCs sit roughly 5-10x lower: EFR32MG24 EM2 ~1.3 µA, CC2652R
  standby ~0.94 µA, nRF52840 ~2.35 µA. If multi-year coin-cell runtime is the
  requirement, the ESP32 is the wrong part and no firmware language fixes that.

## Protocol support per firmware language (ESP32)

| Option | Zigbee | Thread | Matter | Toolchain weight |
|---|---|---|---|---|
| C / ESP-IDF | full, vendor Zigbee SDK | full (OpenThread) | full (vendor Matter SDK) | heavy |
| Rust / esp-rs | raw 802.15.4 MAC only, unstable | via ESP-IDF bindings, or rs-matter | rs-matter, no_std, API unstable | medium |
| Elixir / AtomVM | none | none | none | medium |
| MicroPython | none mainline | none mainline | none | light |
| ESPHome | end devices, basic clusters | since OpenThread support | third-party alpha only | light |

Rules:

- Zigbee on ESP32 is C-only in practice: the vendor stack ships as a prebuilt
  proprietary binary with C headers, so it can be consumed via FFI but not
  ported, audited or fixed. No Rust/Elixir/MicroPython Zigbee stack exists.
- ESPHome's Zigbee component builds end devices only (no router, no
  coordinator), basic clusters only, no OTA over Zigbee, and a config change
  needs a re-pair. H2 is reported more reliable than C6 for it.
- Matter over Thread on ESP32: the vendor SDK's default low-power config is not
  usable as-is. A Thread ICD can wake every second from lwIP IPv4 cyclic timers
  (etharp/dhcp/nd6), and that single source dominates the whole power budget
  (order of 300 µA average against a ~50 µA light-sleep floor). For a
  Thread-only Matter device, disable IPv4 in lwIP and verify the ICD slow-poll
  interval before trusting any sleep number.
- The intermittent-connection model (ICD, and Long Idle Time in later spec
  revisions) is what makes battery Matter devices possible at all. The mechanism
  exists on ESP32 but its defaults need auditing per build.
- Shipping a Matter product needs a real Device Attestation Certificate from a
  PAI plus certification. SDK examples ship test credentials that are not
  shippable; personal builds can ignore this, products cannot.

## Elixir on embedded: Nerves vs AtomVM

- **Nerves** = Buildroot Linux + the BEAM. It targets Linux-class boards only:
  Raspberry Pi family, BeagleBone, generic x86_64, OSD32MP1, GRiSP2, MangoPi MQ
  Pro. It cannot run on an ESP32 because the ESP32 has no MMU and cannot run
  Linux. This is a structural limit, not a support gap — never suggest waiting
  for it.
- **AtomVM** = a from-scratch minimal BEAM that runs `.beam` files on
  microcontrollers (ESP32 family, STM32, RP2, WebAssembly). It implements a
  subset of BEAM opcodes and a small subset of the OTP standard library, is
  pre-1.0, and its own docs say not to use it for mission-critical applications.
- Consequence for a shared codebase: Nerves and AtomVM are different VMs. You do
  not get one Elixir deployment story across a Linux hub and an ESP32 node — you
  get a shared *language* and shared pure-function modules, nothing more.
- AtomVM networking: Wi-Fi STA/AP/STA+AP, `gen_tcp`/`gen_udp`. IPv6 is not
  supported. Deep sleep exists (GPIO wakeup on C3/C6) but the VM reboots on every
  wake, so a VM and deep sleep are inherently at odds.
- AtomVM MQTT is an ESP32-only *port* compiled into the VM image rather than a
  plain application dependency, with TCP/TLS/WebSocket/WSS and client-cert auth.
  It is a small, low-activity component: check its maintenance state before
  depending on it.

## MQTT as the integration surface

- MQTT reaches Home Assistant natively via MQTT discovery, and openHAB
  automatically through its "Home Assistant MQTT Components" binding, which
  consumes the same discovery topics. One payload serves both ecosystems.
- MQTT does **not** reach Apple Home, Google Home or Alexa directly. Those need
  a bridge (a HomeKit bridge, a Matter bridge exposing the automation platform's
  entities, or a vendor cloud).
- Discovery payload essentials: topic
  `homeassistant/<component>/<node_id>/<object_id>/config`, retained; include
  `unique_id` (entity registry), `state_topic`, and a `device` block with
  `identifiers` to group entities under one device. Set `name` to null to inherit
  the device name. Add `availability_topic` with
  `payload_available`/`payload_not_available` and `expire_after` for devices that
  sleep. Use `json_attributes_topic` for metrics with no matching device class.
  The broker must support MQTT v5 (Mosquitto does).
- Arbitrary or custom metrics have no Matter equivalent — vendor-specific
  clusters are invisible to ecosystems. Matter is for reach and control; MQTT is
  for data. Choose per half of the problem.

## Matter ecosystem reach caveat

- Multi-admin lets one device join Home Assistant, Apple Home, Google Home,
  Alexa, SmartThings and IKEA simultaneously, each with its own fabric, with no
  cloud in the path. This is the main argument for Matter over a bridge.
- Platform spec support lags unevenly: Home Assistant tracks the newest spec
  fastest, Apple and Google trail, Alexa trails most. Sensor device types are
  where the gaps bite — air-quality and water-leak sensors are not uniformly
  supported across ecosystems. Check the specific device type against the
  specific ecosystem before designing around Matter.
- Commissioning is a real cost: Home Assistant runs a separate Matter server
  process and commissioning needs a phone companion app; the appliance-style
  install is strongly recommended.

## Shared-codebase tiers (device + server)

| Tier | Rust | Elixir |
|---|---|---|
| Shared wire types, topic/schema, validation | yes | yes (pure modules) |
| Shared business logic (policy, calibration, state machines) | yes | pure functions only, nothing OTP-heavy |
| Shared runtime / same VM on both ends | n/a | only if both ends are Linux |

- Rust delivers the first two tiers from one workspace: a `no_std` protocol crate
  with serde (`default-features = false`, `derive` + `alloc`) compiles for both
  the MCU and the server, so a schema change breaks the build instead of the
  network.
- The honest Elixir alternative is a shared *contract* (JSON Schema or Protobuf)
  rather than shared source, unless both ends are Linux.
- Practical rule: transport protocols (MQTT, Matter, Thread) are the seam. Keep
  the seam protocol-level, and never couple the server language choice to the
  firmware language choice unless shared types are an explicit goal.
