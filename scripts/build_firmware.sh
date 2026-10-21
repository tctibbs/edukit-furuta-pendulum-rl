#!/usr/bin/env bash
# Build one firmware image from the working tree under firmware/, with the board code
# compiled alongside. The generated makefiles carry absolute paths from the machine that
# generated them and never rebuild after a header change, so this compiles the files that
# matter by hand and uses make only to link. See docs/runbooks/edukit-firmware.md.
#
# Usage: build_firmware.sh <mode letter> <out.bin>
#
# The mode letter is written into IDENT_AUTOSTART_MODE in edukit_system.h before the
# compile; the header keeps it afterwards, which is the record of what the image boots.
# Mode x, the showcase, also links the carousel, the OLED and buzzer glue, the policy
# table, the hardware tests' measurement code and the HAL's I2C driver; every other mode
# leaves them out of the link.
set -euo pipefail

mode=${1:?mode letter}
out=${2:?output .bin path}
case "$out" in /*) ;; *) out="$PWD/$out" ;; esac
repo=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
project="$repo/firmware/Edukit_Rotary_Inverted_Pendulum_Project/Edukit_Rotary_Inverted_Pendulum_Project/Projects/Multi/Examples/MotionControl/IHM01A1_ExampleFor1Motor"
debug="$project/SW4STM32/STM32F401RE-Nucleo/Debug"
toolchain="${ARM_TOOLCHAIN:-$HOME/.local/arm-gnu-toolchain/bin}"
export PATH="$toolchain:$PATH"

command -v arm-none-eabi-gcc >/dev/null || { echo "arm-none-eabi-gcc not on PATH; set ARM_TOOLCHAIN" >&2; exit 1; }
test -d "$debug" || { echo "firmware tree not found at $project" >&2; exit 1; }

# Select the mode in the header.
header="$project/Inc/edukit_system.h"
python3 - "$header" "$mode" <<'PY'
import re, sys
path, mode = sys.argv[1], sys.argv[2]
text = open(path).read()
new, n = re.subn(r"(#define IDENT_AUTOSTART_MODE\s+)'.'", lambda m: m.group(1) + f"'{mode}'", text)
if n != 1:
    sys.exit("IDENT_AUTOSTART_MODE not found exactly once in the header")
open(path, "w").write(new)
PY

# The makefiles' and dependency files' absolute prefix: whatever precedes the firmware
# tree becomes this checkout, in every file make reads. See scripts/firmware_prefix.py.
python3 "$repo/scripts/firmware_prefix.py" "$debug" "$repo"

cd "$debug"
inc="-I../../../Inc -I$repo/board"
drivers=../../../../../../../../Drivers
for d in BSP/STM32F4xx-Nucleo BSP/X-NUCLEO-IHMxx BSP/Components/Common BSP/Components/l6474 CMSIS/Include CMSIS/Device/ST/STM32F4xx/Include STM32F4xx_HAL_Driver/Inc; do
    inc="$inc -I$drivers/$d"
done
flags="-mcpu=cortex-m4 -std=gnu11 -g3 -DUSE_HAL_DRIVER -DSTM32F401xE -DUSE_STM32F4XX_NUCLEO -DNUCLEO_F401RE -DSTM32F401RETx -DSTM32 -DSTM32F4 -DDEBUG -c -O0 -ffunction-sections -Wall -fstack-usage -mfpu=fpv4-sp-d16 -mfloat-abi=hard -mthumb"
board="-ffp-contract=off -Wextra -Werror"

# The files that must always be recompiled: main.c reads the header, the board files are
# ours, and the IHM01A1 board driver carries the step-clock fix. -ffp-contract=off, which
# the host harnesses in tests/ pass too, keeps the board arithmetic bit-for-bit with the
# host-tested float32, libm's sinf, cosf, atan2f and hypotf aside.
arm-none-eabi-gcc "$project/Src/main.c" $flags $inc -o Example/User/main.o
arm-none-eabi-gcc "$drivers/BSP/X-NUCLEO-IHMxx/x_nucleo_ihm01a1_stm32f4xx.c" $flags $inc -o Drivers/BSP/STM32F4xx-Nucleo/x_nucleo_ihm01a1_stm32f4xx.o
arm-none-eabi-gcc "$repo/board/policy.c" $flags $board $inc -o Example/User/policy.o
arm-none-eabi-gcc "$repo/board/observer.c" $flags $board -std=c99 $inc -o Example/User/observer.o
objects=(Example/User/policy.o Example/User/observer.o)

# The showcase's objects. The I2C driver is compiled with its module switched on here
# rather than in the shared HAL configuration, so no other mode's build changes.
showcase=(display font5x7 showcase showcase_screens showcase_table showcase_probe showcase_port_stm32 stm32f4xx_hal_i2c)
if [ "$mode" = x ]; then
    for name in display font5x7 showcase showcase_screens showcase_table showcase_probe; do
        arm-none-eabi-gcc "$repo/board/$name.c" $flags $board -std=c99 $inc -o "Example/User/$name.o"
    done
    arm-none-eabi-gcc "$repo/board/showcase_port_stm32.c" $flags -Werror -DHAL_I2C_MODULE_ENABLED $inc -o Example/User/showcase_port_stm32.o
    arm-none-eabi-gcc "$drivers/STM32F4xx_HAL_Driver/Src/stm32f4xx_hal_i2c.c" $flags -w -DHAL_I2C_MODULE_ENABLED $inc -o Example/User/stm32f4xx_hal_i2c.o
    for name in "${showcase[@]}"; do objects+=("Example/User/$name.o"); done
else
    for name in "${showcase[@]}"; do
        grep -v -x -F "\"Example/User/$name.o\"" objects.list > objects.list.tmp || true
        mv objects.list.tmp objects.list
    done
fi
for obj in "${objects[@]}"; do
    grep -q "\"$obj\"" objects.list || echo "\"$obj\"" >> objects.list
done

rm -f STM32F401RE-Nucleo.elf
make --no-print-directory all >/dev/null
arm-none-eabi-objcopy -O binary STM32F401RE-Nucleo.elf STM32F401RE-Nucleo.bin
mkdir -p "$(dirname "$out")"
cp STM32F401RE-Nucleo.bin "$out"

arm-none-eabi-size STM32F401RE-Nucleo.elf
echo "wrote $out ($(stat -f %z "$out" 2>/dev/null || stat -c %s "$out") bytes), mode '$mode'"
# The banner is stored as the format string "BUILD %s (%s)", so print the build note itself.
grep -a -o -m1 "retuned swing-up; modes [^[:cntrl:]]*\|mode x; [^[:cntrl:]]*" STM32F401RE-Nucleo.bin | head -1 || true
grep -a -c "AUTOSTART mode" STM32F401RE-Nucleo.bin >/dev/null && echo "autostart banner present"
if [ "$mode" = x ]; then
    grep -a -c "SHOWCASE result" STM32F401RE-Nucleo.bin >/dev/null && echo "showcase result line present"
fi
