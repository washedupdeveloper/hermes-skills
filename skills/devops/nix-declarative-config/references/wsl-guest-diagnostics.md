# Diagnosing the WSL guest, and the Windows host behind it

The sandbox runs as a container inside the host's WSL2 VM, so the guest's own
facts are readable from inside it. They are the *guest's*, never the sandbox's:
they are what WSL handed the VM. Everything the VM cannot answer -- firmware,
power, the Windows processor count -- needs the user to run a command on Windows,
so the deliverable is discriminating commands, not a verdict.

## What to read, and what each fact means

| Read | Tells you |
| --- | --- |
| `cat /proc/cmdline` | the kernel line WSL built for this boot, including `nr_cpus=<n>` |
| `lscpu` | `Thread(s) per core`, `Core(s) per socket`, sockets -- the guest's view |
| `/proc/uptime` | how long the VM has been up; compare with the session's start to see whether WSL restarted |
| `free -h` | guest RAM and swap |
| `df -h` | the VHDX filesystem, not the Windows volume |
| `uname -r` | which WSL kernel build is running |

`nr_cpus=<n>` is the count WSL **resolved**, after clamping the configured value
to what Windows reports. So it is the best available read of what WSL decided it
was told -- and it is not by itself evidence of what the host exposes.

## Reading the processor warning

The message is `wsl2.processors cannot exceed the number of logical processors on
the system ({} > {})`, i.e. `(configured > available)`: the first number is what
the configuration asked for, the second is what Windows reported. Which is which
decides the diagnosis:

- **Second number is the host's real total** (e.g. `(6 > 24)` on a 24-thread CPU):
  the warning is WSL's own bug and WSL is obeying the configuration. The 2.4.5
  through 2.4.7 releases emit it for *any* configured value; it was fixed in
  2.4.8. Treat it as noise on those versions, not as a host fault.
- **Second number is below the CPU's logical processor count**: Windows itself is
  exposing fewer processors. That is host-side -- firmware, or a boot-time
  processor cap (`msconfig` -> Boot -> Advanced options -> Number of processors,
  or `bcdedit /enum "{current}"`, `numproc`).

Read the text and the logic from the source, not from a paraphrase of the
message: the exact string is in the WSL repository's
`localization/strings/en-US/Resources.resw` under `MessageTooManyProcessors`;
`Config::Initialize` in `src/windows/common/WslCoreConfig.cpp` is where the clamp
and the warning happen; `AppendCommonKernelCommandLine` in
`src/windows/common/helpers.cpp` is what emits `nr_cpus=`.

## Recognising WSL's own defaults

If the guest shows a memory total of half the host's RAM and a 4 GiB swap, those
are WSL's defaults, not the user's settings -- so `.wslconfig` customises at most
what differs from them. Say which numbers are defaults before treating any of them
as a configured value.

## When the machine dies during a switch

A switch evaluates, builds and activates; none of those can remove power from the
Windows host, and on NixOS-WSL there is no bootloader step to reach firmware setup
(`installBootLoader = true`, Microsoft kernel). Establish that from the tree
first:

```console
grep -rnE 'boot\.loader|kernelParams|swapDevices|zram' --include='*.nix' .
```

What a switch *can* do is impose load, and that is the part to test. Separate the
two halves so the result is attributable:

```console
nix build .#nixosConfigurations.<host>.config.system.build.toplevel \
  --max-jobs 2 --cores 2 --keep-going
nh os switch          # activation only, now that the build is done
```

Dying during the build is load; dying during activation is something else. To
remove the load as a variable rather than test it, cap it declaratively in the
**machine's own** configuration (`nix.settings.max-jobs` / `cores` in
`machines/<host>/configuration.nix`) so a switch cannot spike the box -- not in
the shared baseline module, where a value chosen for one host silently becomes
policy for every machine. The cap only exists after a switch, so the first one
passes the same limits on the command line; and `cores` sets `NIX_BUILD_CORES`,
which make and ninja honour but a derivation that spawns its own parallelism
(npm/Node, some Rust builds) may not -- it lowers the peak, it does not bound it.

A report dated "never happened until this week" is answered by what changed this
week: file mtimes in the tree, `git log --since`, and any firmware or Windows
update on the host. A **BIOS update or CMOS clear is the single hypothesis that
explains a changed core count *and* new instability at once** -- it resets the
CPU preset and the memory profile together -- so ask whether one happened before
treating the two symptoms as unrelated. The heaviest build a Hermes switch can add
is the Electron desktop -- an npm package build with `node-pty` compiled against
`electron.headers` -- which is worth naming when the machine has few vCPUs.

### When it dies even at a capped build, stop and call it hardware

A build held to a handful of threads on a many-core CPU cannot kill a healthy
machine, so a crash there is not a load problem to tune around: the cap has
already exonerated the tree. Confirm from the guest that the shutdown was unclean,
which is what makes it a power event rather than a software one:

```console
dmesg | grep -iE 'ext4|recovery|I/O error'   # "recovery complete" = journal replay = unclean cut
git fsck --no-progress --full                # an "object corrupt or missing" is crash damage
```

A crash can leave a git object zero bytes long. **Back the repository up off the
machine before the next attempt**, and check whether the damaged object is
reachable (`git rev-list --objects HEAD | grep <oid>`) before saying what was
lost -- an unreachable object means nothing was.

Ranked causes for an instant cut with no BSOD and no WHEA entry: memory
instability (the EXPO/XMP profile failing at its rated speed, which also explains
the failed POST that follows), then power delivery (PSU, cables, VRM protection).
A CPU-only build leaves the GPU idle, so the load sits on the CPU rail. Thermal
trips are the least likely -- they shut down and stay down rather than landing in
setup.

Two host details test the memory hypothesis cheaply: `Win32_PhysicalMemory`
showing `ConfiguredClockSpeed` above `Speed` means the RAM is on an overclock
profile rather than JEDEC, and the board's BIOS release notes often name the
failure outright (ASUS B850 notes for AGESA 1.3.0.x cite "potential boot failures
and stability issues observed on certain Ryzen 9000 configurations" and extra
"stability margin during high-frequency DDR5 training"). The decisive test is one
BIOS change: **disable EXPO/XMP so the RAM runs JEDEC**, then retry. Stable means
the profile; still dying means power delivery.

"Reboots into BIOS setup, drives still listed but boot order gone" is a failed
POST, not a second fault -- the board failed memory training, fell back to safe
mode, and the NVRAM boot entries went with it. Ask which **Q-LED** is lit (DRAM
points at training) and read the message on the setup screen: that message names
the cause, and it is the single most informative thing the user can report. If
BitLocker is on, repeated loss of the boot configuration can eventually demand a
recovery key, so confirm the key is saved or suspend it while testing.

## Host-side evidence to hand over

Each command separates hypotheses; say what each result would mean.

```console
Get-CimInstance Win32_Processor | Format-List Name,NumberOfCores,NumberOfLogicalProcessors
Get-CimInstance Win32_ComputerSystem | Format-List NumberOfProcessors,NumberOfLogicalProcessors
Get-Content $env:USERPROFILE\.wslconfig
wsl --version
bcdedit /enum "{current}" | findstr /i numproc
Get-WinEvent -FilterHashtable @{LogName='System'; Id=41,1001,6008,17,18,19} -MaxEvents 40 |
  Format-Table TimeCreated,Id,ProviderName -Auto
```

Id 41 is Kernel-Power -- written *after* the reboot, so it says only that the
previous shutdown was not clean and never names a cause. Read the interval between
occurrences instead: a shortening gap is a deteriorating condition. 1001 is a
bugcheck, 6008 an unexpected shutdown, 1074/109 a software-initiated one, and
17/18/19 are WHEA-Logger (machine-check and corrected errors), which point at
hardware.

Query WHEA with a **wildcard**. The provider is `Microsoft-Windows-WHEA-Logger`,
so `? ProviderName -like 'WHEA'` is an exact match that returns nothing whether or
not errors exist; `-like '*WHEA*'` is the form that answers. A zero-row result
from the wrong query reads as "no hardware errors" and is worth double-checking
before it is believed.

## When the guest reports fewer cores than the CPU has

A reduced core count is usually a **firmware** state, not a WSL or OS one. The
two independent reads below separate the possible causes before anyone touches
the configuration.

**The CPU brand string is not a core count.** `Win32_Processor.Name`, Task
Manager's CPU title and the BIOS main page all print the marketing string
("AMD Ryzen 9 9900X3D 12-Core Processor") however many cores are actually
enabled -- the string is burned into the part. Read `NumberOfCores` /
`NumberOfLogicalProcessors`, or `lscpu` in the guest. A BIOS screen reading
"12 core cpu" confirms nothing.

**The core/thread pair names the fault:**

| Guest shows | Meaning |
| --- | --- |
| N cores, 2N logical, reduced L3 | one CCD parked, SMT still on |
| N cores, N logical, reduced L3 | one CCD parked **and** SMT disabled -- a single preset doing both |
| full cores, N logical | SMT disabled only |

**L3 capacity is the independent fingerprint on a dual-CCD part.** A 9900X3D is
128 MB total: 96 MB on the V-Cache CCD (32 MB native + 64 MB stacked) plus 32 MB
on the plain CCD. A guest showing half the cores *and* 96 MB L3 is running one
CCD. Corroborate with the L2 instance count (one per core) and contiguous
`core_id`s under `/sys/devices/system/cpu/cpu*/topology/`.

The preset that does this is named per vendor -- MSI "X3D Gaming Mode", Gigabyte
"X3D Turbo Mode", ASUS "X3D Turbo Mode" (older BIOSes: "Game Mode"), ASRock
"X3D Optimized Mode". It is often enabled by default, and a BIOS update can
restore it. Its companion settings do **not** reset when the mode is toggled off,
so they must be set explicitly: the second-CCD control ("CCD1 Core Control",
"Downcore Control") back to Auto, and SMT back to Enabled. Accept only the full
count -- 12 cores with 12 logical means SMT is still off.

Two things that are *not* corroboration. Every tool reading the **OS** processor
count agrees with the reduced number (Task Manager, AMD Adrenalin, WMI), so a
second opinion has to come from a CPUID reader (CPU-Z, HWiNFO) or from `lscpu` in
the guest. And the sandbox has no DMI -- `/sys/class/dmi/id/*` is absent and there
is no `dmidecode` -- so the board model and BIOS date come from `Win32_BaseBoard`
and `Win32_BIOS`, not from here.

One artifact not to misread: the guest reports L3 as a single instance shared
across every vCPU (`shared=0-23`) even when the CPU has two CCDs. That is how
Hyper-V presents it, not evidence about the CCDs.

## What not to conclude

- Do not read `nr_cpus` as proof of what the host exposes, and do not read the
  processor warning as proof of a fault -- get both numbers first.
- A guest-side fact never settles a host-side question. When the evidence needed
  lives on Windows, hand over the commands and say which answer means which cause
  instead of naming a cause you cannot see.
